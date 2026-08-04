"""CodeRunner —— 带 sandbox 的 BaseRunner 子类。

需要沙箱（本地 / Docker / SSH）来执行代码和文件操作，
先打开 thread，再打开 thread 里的 sandbox；对话自动持久化，sandbox tools 自动注入。

配置来源优先级：代码参数 > 配置文件 > 默认值。

sandbox 初始化有两种时序，配置入口统一在 ``__init__``：

- 懒初始化：``CodeRunner(agent, backend="local")``，sandbox 在首次 ``run`` 前打开。
- 立即初始化：``await CodeRunner.create(agent, backend="local")``，返回时 sandbox 已就绪。

``create`` 只是「构造 + ensure_initialized」，参数与 ``__init__`` 一致；``from_toml``
把 TOML 解析成 spec 后复用 ``create``，两条立即初始化路径共用同一实现。

用法::

    # 本地沙箱；第一次 run 前会自动打开 sandbox
    r = CodeRunner(agent, backend="local")

    # Docker 沙箱
    r = CodeRunner(agent, backend="docker", image="python:3.12")

    # SSH 远端沙箱
    r = CodeRunner(agent, backend="ssh", ssh_host="dev-server")

    # 显式提前初始化
    r = await CodeRunner.create(agent, backend="local")

    # 从配置文件；返回时已初始化
    r = await CodeRunner.from_toml("code.toml", agent)
"""

from __future__ import annotations

import asyncio
import tomllib
from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from pathlib import Path

from ..core.agent import Agent
from ..core.message import Messages
from ..core.tool import FunctionTool
from ..ithread import ThreadSpec
from ..skills.runtime import SkillRuntime
from .base_runner import BaseRunner, _run_capabilities, assemble_run_resources
from .helper import ArunReturnType, EventHandler
from .thread import Thread


def build_code_agent(
    agent: Agent,
    *,
    system_prompt: str,
    tools: list[FunctionTool],
) -> Agent:
    """重新构造 Agent，让 tools / tool_schemas / tool_map 保持一致。"""
    return Agent(
        agent.provider,
        system=system_prompt,
        tools=[*agent.tools, *tools],
        max_turns=agent.max_turns,
    )


class CodeRunner(BaseRunner):
    """带 sandbox 的 BaseRunner 子类。

    配置来源（优先级从高到低）：

    1. 代码参数（backend / image / ssh_host 等）
    2. 配置文件（TOML，通过 from_toml 加载）
    3. 默认值（local sandbox + .electromind/threads/）
    """

    def __init__(
        self,
        agent: Agent,
        *,
        # sandbox 配置
        backend: str = "local",
        image: str | None = None,
        container_ttl_seconds: int | None = None,
        ssh_host: str | None = None,
        ssh_config: str = "~/.ssh/config",
        ssh_workdir: str = "~/.electromind",
        command_policy: str = "workdir",
        # thread / conversation 配置
        thread_id: str | None = None,
        conversation_id: str | None = None,
        root: str | Path | None = None,
        conversation_root: str = ".",
        conv_backend: str = "jsonl",
        messages: Messages | None = None,
        # skills + tools
        skill_roots: list[str | Path] = (),
        tools: list[FunctionTool] = (),
        extra_system: str = "",
        spec: ThreadSpec | None = None,
        builtin_roots: Sequence[str | Path] | None = None,
    ):
        """创建 CodeRunner；sandbox 在第一次 run 前自动初始化。"""
        resolved_thread_id = (
            thread_id
            or conversation_id
            or datetime.now().strftime("thread-%Y%m%d-%H%M%S")
        )
        resolved_spec = spec or ThreadSpec(
            conversation_backend=conv_backend,
            conversation_root=conversation_root,
            backend=backend,
            image=image,
            container_ttl_seconds=container_ttl_seconds,
            ssh_host=ssh_host,
            ssh_config=ssh_config,
            ssh_workdir=ssh_workdir,
            command_policy=command_policy,
        )
        thread = Thread.open(
            resolved_thread_id, root=root, overrides=resolved_spec.__dict__
        )

        BaseRunner.__init__(self, agent, thread, messages=messages)
        self.sandbox = None
        self.code_initialized = False
        self.init_lock = asyncio.Lock()
        self.base_agent = agent
        self.pending_skill_roots = list(skill_roots)
        self.pending_tools = list(tools)
        self.pending_extra_system = extra_system
        self.pending_builtin_roots = (
            tuple(builtin_roots) if builtin_roots is not None else None
        )

    async def ensure_initialized(self) -> None:
        """确保 sandbox、skills 和 sandbox tools 已经绑定到 Agent。

        首次 ``run`` 之前 ``self.agent`` 是构造时传入的 ``base_agent``（不含
        sandbox tools / skills system prompt）；初始化后由 ``build_code_agent``
        重建为带完整工具与系统提示的 agent。因此不要在 ``run`` 之前依赖
        ``self.agent.tools``。
        """
        if self.code_initialized:
            return

        async with self.init_lock:
            if self.code_initialized:
                return

            resources = await assemble_run_resources(
                self.thread,
                skill_roots=self.pending_skill_roots,
                tools=self.pending_tools,
                extra_system=self.pending_extra_system,
                agent_system=self.base_agent.system,
                run_state=self.run_state,
                builtin_roots=self.pending_builtin_roots,
            )
            self.agent = build_code_agent(
                self.base_agent,
                system_prompt=resources.system_prompt,
                tools=resources.tools,
            )
            self.sandbox = resources.sandbox
            self.skills = resources.skills
            # Phase-2: establish the shared SkillRuntime so subsequent turns
            # refresh generations via before_user_turn (was previously None).
            self.skill_runtime = SkillRuntime(
                self.thread.spec.project_path,
                configured_roots=self.pending_skill_roots,
                mounter=_runtime_mounter(resources),
                builtin_roots=self.pending_builtin_roots,
                service=resources.catalog_service,
                capabilities=_run_capabilities(self.thread.spec),
            )
            self.skill_runtime.prepare_turn()
            self.code_initialized = True

    async def run(
        self,
        user_input: str,
        *,
        return_type: ArunReturnType = "event",
        event_handler: EventHandler | None = None,
        **run_kwargs,
    ) -> AsyncIterator:
        await self.ensure_initialized()
        async for item in super().run(
            user_input,
            return_type=return_type,
            event_handler=event_handler,
            **run_kwargs,
        ):
            yield item

    async def close(self) -> None:
        if not self.code_initialized:
            close_store = getattr(self.store, "close", None)
            if callable(close_store):
                close_store()
            return
        await super().close()

    @classmethod
    async def create(cls, agent: Agent, **kwargs) -> CodeRunner:
        """构造 CodeRunner 并立即打开 sandbox、加载 skills（立即初始化路径）。

        参数与 ``__init__`` 完全一致（backend / image / thread_id / tools 等），此处
        只透传，不重复声明，保证配置入口唯一。与直接构造的区别仅在时序：``create``
        返回时 sandbox 已就绪，构造器则等到首次 ``run``。

        Args:
            agent: 基础 Agent；sandbox tools 与 skills 会在初始化时合并进来。
            **kwargs: 透传给 ``__init__`` 的配置项。

        Returns:
            已完成 sandbox / skills 初始化的 CodeRunner。

        用法::

            r = await CodeRunner.create(agent, backend="docker", image="python:3.12")
            async for text in r.run("写个快排", return_type="text"):
                print(text)
            await r.close()
        """
        runner = cls(agent, **kwargs)
        await runner.ensure_initialized()
        return runner

    @classmethod
    async def from_toml(
        cls,
        path: str | Path,
        agent: Agent,
        *,
        thread_id: str | None = None,
        conversation_id: str | None = None,
        root: str | Path | None = None,
        skill_roots: list[str | Path] = (),
        tools: list[FunctionTool] = (),
        extra_system: str = "",
        builtin_roots: Sequence[str | Path] | None = None,
    ) -> CodeRunner:
        """从 TOML 配置文件创建并打开 CodeRunner（立即初始化路径）。

        解析出 ThreadSpec 后交给 ``create``，thread_id 兜底与 sandbox 初始化都复用
        构造器与 ``create``，不在此重复。

        配置文件格式同 ThreadSpec：

            [conversation]
            backend = "jsonl"
            root = "."

            [sandbox]
            backend = "docker"
            image = "python:3.12"

            [agent]
            model = "deepseek-v4-flash"
            system = "你是一个代码助手"
        """
        with Path(path).open("rb") as fp:
            payload = tomllib.load(fp)
        spec = ThreadSpec.from_dict(payload)
        return await cls.create(
            agent,
            thread_id=thread_id,
            conversation_id=conversation_id,
            root=root,
            skill_roots=skill_roots,
            tools=tools,
            extra_system=extra_system,
            spec=spec,
            builtin_roots=builtin_roots,
        )


def _runtime_mounter(resources) -> "object | None":
    """The lazy mounter for the runtime's activation service.

    SSH backends use ``SshLazySkillMounter`` (full snapshot digest
    verification); local/container use ``LazySkillMounter``.
    """
    from ..skills.mounting import LazySkillMounter, SshLazySkillMounter
    from ..skills.snapstore import PrivateSnapshotStore

    sandbox = resources.sandbox
    if sandbox is None:
        return None
    store = PrivateSnapshotStore()
    backend = getattr(sandbox, "backend", None)
    backend_name = getattr(getattr(backend, "__class__", None), "__name__", "")
    if backend_name == "SshBackend":
        return SshLazySkillMounter(sandbox, store=store)
    return LazySkillMounter(sandbox, store=store)

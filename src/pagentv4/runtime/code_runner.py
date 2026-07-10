"""CodeRunner —— 带 sandbox 的 BaseRunner 子类。

需要沙箱（本地 / Docker / SSH）来执行代码和文件操作，
先打开 thread，再打开 thread 里的 sandbox；对话自动持久化，sandbox tools 自动注入。

配置来源优先级：代码参数 > 配置文件 > 默认值。

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
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

from ..core.agent import Agent
from ..core.message import Messages
from ..core.tool import FunctionTool
from ..ithread import IThread, ThreadSpec
from ..sandbox import Sandbox
from ..skills import SkillRegistry, build_skills_system_prompt, make_use_skill_tool
from .base_runner import BaseRunner
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


async def open_code_resources(
    thread: IThread,
    *,
    skill_roots: list[str | Path],
    tools: list[FunctionTool],
    agent_system: str | None,
    extra_system: str,
) -> tuple[Sandbox, SkillRegistry, str, list[FunctionTool]]:
    sandbox = await thread.open_sandbox()
    combined_tools = [*sandbox.tools(), *tools]

    skills = SkillRegistry.from_defaults(*skill_roots)
    mount = await sandbox.install_skills(skills) if skills.names() else {}
    if skills.names():
        combined_tools.append(make_use_skill_tool(skills, mount))

    computer_desc = await sandbox.describe()
    skills_prompt = build_skills_system_prompt(skills, mount)
    system_tail = thread.spec.system or extra_system or agent_system
    system_prompt = "\n".join(
        part for part in (computer_desc, skills_prompt, system_tail) if part
    )
    return sandbox, skills, system_prompt, combined_tools


class CodeRunner(BaseRunner):
    """带 sandbox 的 BaseRunner 子类。

    配置来源（优先级从高到低）：

    1. 代码参数（backend / image / ssh_host 等）
    2. 配置文件（TOML，通过 from_toml 加载）
    3. 默认值（local sandbox + .pagent/threads/）
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
        ssh_workdir: str = "~/agent",
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

            sandbox, skills, system_prompt, combined_tools = await open_code_resources(
                self.thread,
                skill_roots=self.pending_skill_roots,
                tools=self.pending_tools,
                agent_system=self.base_agent.system,
                extra_system=self.pending_extra_system,
            )
            self.agent = build_code_agent(
                self.base_agent,
                system_prompt=system_prompt,
                tools=combined_tools,
            )
            self.sandbox = sandbox
            self.skills = skills
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
    async def create(
        cls,
        agent: Agent,
        *,
        # sandbox 配置
        backend: str = "local",
        image: str | None = None,
        container_ttl_seconds: int | None = None,
        ssh_host: str | None = None,
        ssh_config: str = "~/.ssh/config",
        ssh_workdir: str = "~/agent",
        command_policy: str = "workdir",
        # thread / conversation 配置
        thread_id: str | None = None,
        conversation_id: str | None = None,
        root: str | Path | None = None,
        conversation_root: str = ".",
        conv_backend: str = "jsonl",
        # skills + tools
        skill_roots: list[str | Path] = (),
        tools: list[FunctionTool] = (),
        extra_system: str = "",
    ) -> CodeRunner:
        """创建 CodeRunner 并立即打开 sandbox、加载 skills。

        用法::

            r = await CodeRunner.create(agent, backend="docker", image="python:3.12")
            async for text in r.run("写个快排", return_type="text"):
                print(text)
            await r.close()
        """
        runner = cls(
            agent,
            backend=backend,
            image=image,
            container_ttl_seconds=container_ttl_seconds,
            ssh_host=ssh_host,
            ssh_config=ssh_config,
            ssh_workdir=ssh_workdir,
            command_policy=command_policy,
            thread_id=thread_id,
            conversation_id=conversation_id,
            root=root,
            conversation_root=conversation_root,
            conv_backend=conv_backend,
            skill_roots=skill_roots,
            tools=tools,
            extra_system=extra_system,
        )
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
    ) -> CodeRunner:
        """从 TOML 配置文件创建并打开 CodeRunner。

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
        resolved_thread_id = (
            thread_id
            or conversation_id
            or datetime.now().strftime("thread-%Y%m%d-%H%M%S")
        )
        runner = cls(
            agent,
            thread_id=resolved_thread_id,
            root=root,
            skill_roots=skill_roots,
            tools=tools,
            extra_system=extra_system,
            spec=spec,
        )
        await runner.ensure_initialized()
        return runner

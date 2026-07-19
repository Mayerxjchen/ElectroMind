"""BaseRunner —— 根据 spec 动态开资源的 Agent Runner。

BaseRunner 接受一个 thread，里面带着 ThreadSpec、conversation store 和 workspace。
所有持久化资源都从 thread 出发，避免出现"没有 thread 但单独挂 conversation"的落盘形态。

循环骨架（`execute_tool` / `stream_agent_events` / `emit` / `emit_tool_events` /
`run`）继承自 `LoopAdapter`；本类只叠加「持久化」能力：`after_*` 覆写为 flush、
`close` 关 store + sandbox。

BaseRunner 本身不直接被用户使用，由子类暴露具体用法：

- ChatRunner：只要对话持久化，不要 sandbox
- CodeRunner：需要 sandbox（本地 / Docker / SSH）
- 还有只注入自定义工具、不要 sandbox 的场景
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import NamedTuple

from ..conversation import ConversationStore
from ..core.agent import Agent
from ..core.message import Messages
from ..core.provider import ProviderProtocol
from ..core.tool import FunctionTool
from ..ithread import IThread, ThreadSpec
from ..sandbox import Sandbox
from ..skills import (
    SkillRegistry,
    build_skills_system_prompt,
    make_use_skill_tool,
)
from .loop_adapter import LoopAdapter
from .run_state import RunState
from .thread import Thread


class RunResources(NamedTuple):
    """assemble_run_resources 的产物：一次运行所需的资源与提示词。"""

    sandbox: Sandbox | None
    skills: SkillRegistry
    system_prompt: str
    tools: list[FunctionTool]


async def assemble_run_resources(
    thread: IThread,
    *,
    skill_roots: Sequence[str | Path] = (),
    tools: Sequence[FunctionTool] = (),
    extra_system: str = "",
    agent_system: str | None = None,
    run_state: RunState | None = None,
) -> RunResources:
    """打开 thread 声明的 sandbox 与 skills，装配运行所需的工具集与 system prompt。

    三处初始化路径（CodeRunner 懒初始化、BaseRunner.from_spec、Runner.create）共用
    此函数，避免各自拼接 system prompt 时发生漂移。

    ``thread.spec.backend == "none"`` 时不开 sandbox（纯对话），此时 skills 不挂载到
    沙箱、``computer_desc`` 为空。system prompt 由 computer 描述、skills 说明、system
    收尾三段按序拼接；system 收尾取值优先级：``thread.spec.system`` > ``extra_system``
    > ``agent_system``。

    Args:
        thread: 已打开的 thread，提供 spec 与 open_sandbox。
        skill_roots: 追加的 skill 搜索根目录。
        tools: 需要合并进 agent 的外部工具，排在 sandbox tools 之后。
        extra_system: 调用方传入的 system 收尾候选。
        agent_system: 已有 agent 的 system，作为最后兜底（重建已有 agent 时使用）。
        run_state: 若提供，开 sandbox 期间标记为 waking_sandbox，装配完成后回到 idle。

    Returns:
        RunResources：sandbox（backend 为 none 时为 None）、skills、system_prompt、
        合并后的 tools。
    """
    if run_state is not None:
        run_state.phase = "waking_sandbox"

    sandbox: Sandbox | None = None
    combined_tools: list[FunctionTool] = []
    computer_desc = ""
    if thread.spec.backend != "none":
        sandbox = await thread.open_sandbox()
        combined_tools.extend(sandbox.tools())
        computer_desc = await sandbox.describe()
    combined_tools.extend(tools)

    skills = SkillRegistry.from_defaults(*skill_roots)
    mount: dict = {}
    if skills.names():
        if sandbox is not None:
            mount = await sandbox.install_skills(skills)
        combined_tools.append(make_use_skill_tool(skills, mount))

    system_tail = thread.spec.system or extra_system or agent_system
    skills_prompt = build_skills_system_prompt(skills, mount)
    system_prompt = "\n".join(
        part for part in (computer_desc, skills_prompt, system_tail) if part
    )

    if run_state is not None:
        run_state.phase = "idle"
    return RunResources(sandbox, skills, system_prompt, combined_tools)


class BaseRunner(LoopAdapter):
    """挂在 thread 上的 Agent Runner 基类。

    thread 里有什么就开什么，不强制绑定任何特定资源组合。
    子类决定暴露哪些配置入口（代码参数 / TOML / thread 目录）。

    Included:

    - [x] tool execution for Agent.tools + sandbox tools
    - [x] message state + conversation persistence
    - [x] event stream and return_type projection
    - [x] max_turns loop with one synthesis turn
    - [x] sandbox + skills（spec 里配了就开）

    Excluded:

    - [ ] inbound cancel/steer/checkpoint
    - [ ] tool hooks or approval
    """

    def __init__(
        self,
        agent: Agent,
        thread: IThread,
        *,
        store: ConversationStore | None = None,
        messages: Messages | None = None,
        sandbox: Sandbox | None = None,
        skills: SkillRegistry | None = None,
    ):
        super().__init__(agent, messages)
        self.thread = thread
        self.spec = thread.spec
        self.sandbox = sandbox
        self.skills = skills or SkillRegistry()

        self.store = store or thread.open_store()
        self.conversation_id = thread.messages_conversation_id
        self.messages = messages if messages is not None else thread.load_messages()

    async def after_continuing(self, *, turn: int) -> None:
        del turn
        self.flush_conversation()

    async def after_run_end(self, *, turn: int) -> None:
        del turn
        self.messages.complete_orphan_tool_results()
        self.flush_conversation()

    def flush_conversation(self) -> None:
        self.store.save(self.conversation_id, self.messages)

    async def close(self) -> None:
        self.run_state.phase = "closing"
        close_store = getattr(self.store, "close", None)
        if callable(close_store):
            close_store()
        if self.sandbox is not None:
            await self.sandbox.close()
        self.run_state.phase = "idle"

    @classmethod
    async def from_spec(
        cls,
        thread_id: str,
        spec: ThreadSpec,
        provider: ProviderProtocol,
        *,
        root: str | Path | None = None,
        extra_system: str = "",
        max_turns: int = 8,
        skill_roots: Sequence[str | Path] = (),
        tools: Sequence[FunctionTool] = (),
    ) -> BaseRunner:
        """从 ThreadSpec 创建 BaseRunner：根据 spec 配置动态开资源。

        thread 里配了 conversation 就开 store，配了 sandbox 就开 sandbox，
        配了 skills 目录就加载 skills。
        """
        thread = Thread.open(thread_id, root=root, overrides=asdict(spec))

        run_state = RunState(phase="waking_sandbox")
        resources = await assemble_run_resources(
            thread,
            skill_roots=skill_roots,
            tools=tools,
            extra_system=extra_system,
            run_state=run_state,
        )

        runner = cls(
            Agent(
                provider,
                system=resources.system_prompt,
                tools=resources.tools,
                max_turns=max_turns,
            ),
            thread,
            sandbox=resources.sandbox,
            skills=resources.skills,
        )
        runner.run_state = run_state
        return runner

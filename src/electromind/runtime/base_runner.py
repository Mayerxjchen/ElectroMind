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
from ..skills import SkillRegistry
from ..skills.runtime import SkillRuntime
from .loop_adapter import LoopAdapter
from .run_state import RunState
from .thread import Thread


class RunResources(NamedTuple):
    """assemble_run_resources 的产物：一次运行所需的资源与提示词。

    ``catalog_service`` / ``catalog`` are the SHARED discovery state: every
    runner construction path (from_spec / Runner.create / CodeRunner) reuses
    the same service and frozen catalog so generations stay consistent and
    activations consume exactly this catalog's content.
    """

    sandbox: Sandbox | None
    skills: SkillRegistry
    system_prompt: str
    tools: list[FunctionTool]
    catalog_service: "object | None" = None
    catalog: "object | None" = None


def assemble_harness_tools(spec: ThreadSpec) -> list[FunctionTool]:
    """按 ``[agent] tools`` 白名单解析主 agent 的进程内（harness）工具。

    thread.toml 的 ``[agent] tools`` 是唯一事实来源：列出的名字才挂，不列就没有。
    识别的名字：

    - ``web_search`` / ``fetch_url``：网页检索工具。
    - ``delegate_to_subagent``：子 agent 委派工具；还需配了 ``[sub.*]`` 才真正挂上。
    - ``plan_propose`` / ``plan_step_update`` / ``artifact_register``：G1b
      Plan/Artifact 模型工具桥（引擎经 ``engine.accessor`` 访问）。

    未识别的名字直接报错（显式报错胜过静默吞掉写错的配置）。列了
    ``delegate_to_subagent`` 却没配 ``[sub.*]`` 同样报错——一个空 enum 的委派工具
    对模型毫无意义。
    """
    from ..tools.delegate import SUBAGENT_TOOL_NAME, make_subagent_tool
    from ..tools.plan_artifacts import PLAN_TOOL_NAMES, make_plan_tools
    from ..tools.web import fetch_url, web_search

    resolved: list[FunctionTool] = []
    plan_tools: dict[str, FunctionTool] | None = None
    for name in spec.agent_tools:
        if name == "web_search":
            resolved.append(web_search)
        elif name == "fetch_url":
            resolved.append(fetch_url)
        elif name == SUBAGENT_TOOL_NAME:
            if not spec.subs:
                raise ValueError(
                    f"[agent] tools 列出了 {SUBAGENT_TOOL_NAME!r} 但没有配任何 "
                    "[sub.<name>]；请在 thread.toml 里补上子 agent 定义，或去掉该项"
                )
            resolved.append(make_subagent_tool(spec.subs))
        elif name in PLAN_TOOL_NAMES:
            if plan_tools is None:
                plan_tools = {t.name: t for t in make_plan_tools()}
            resolved.append(plan_tools[name])
        else:
            raise ValueError(
                f"[agent] tools 里的 {name!r} 不是已知的 harness 工具；可用："
                "web_search、fetch_url、delegate_to_subagent、plan_propose、"
                "plan_step_update、artifact_register"
            )
    return resolved


async def assemble_run_resources(
    thread: IThread,
    *,
    skill_roots: Sequence[str | Path] = (),
    tools: Sequence[FunctionTool] = (),
    extra_system: str = "",
    agent_system: str | None = None,
    run_state: RunState | None = None,
    builtin_roots: Sequence[str | Path] | None = None,
) -> RunResources:
    """打开 thread 声明的 sandbox 与 skills，装配运行所需的工具集与 system prompt。

    三处初始化路径（CodeRunner 懒初始化、BaseRunner.from_spec、Runner.create）共用
    此函数，避免各自拼接 system prompt 时发生漂移。

    ``thread.spec.backend == "none"`` 时不开 sandbox（纯对话），此时 skills 不挂载到
    沙箱、``computer_desc`` 为空。system prompt 由 computer 描述、skills 说明、system
    收尾三段按序拼接；system 收尾取值优先级：``thread.spec.system`` > ``extra_system``
    > ``agent_system``。

    工具与 skills 都以 thread.toml（``spec``）为来源：

    - harness 工具（web_search / fetch_url / delegate_to_subagent）由 ``[agent] tools``
      白名单决定，见 :func:`assemble_harness_tools`。
    - skills 通过 ``discover_skill_sources(project_path)`` 自动发现项目/用户目录；
      ``[agent] skills`` 和 ``skill_roots`` 作为额外的 configured roots 追加。

    Args:
        thread: 已打开的 thread，提供 spec 与 open_sandbox。
        skill_roots: 追加的 skill 搜索根目录，拼在 ``spec.skills`` 之后（程序化注入用）。
        tools: 需要合并进 agent 的外部工具，排在 sandbox tools 之后（程序化注入用）。
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
    combined_tools.extend(assemble_harness_tools(thread.spec))
    # P0-3: Effect 注册门 —— 内置工具按名补全声明；仍未声明的（自定义工具
    # 未显式声明）拒绝注册到正式 Runner（M4 §9.1 验收）。
    from ..execution.effects import (
        apply_builtin_effects,
        assert_effects_declared,
    )

    combined_tools = apply_builtin_effects(combined_tools)
    assert_effects_declared(combined_tools)

    # Phase-2: discovery runs through the shared catalog service (candidates).
    # No full install at open — skills mount lazily at activation time
    # (RFC section 九: 安装全部 Skill → Activated Skill Lazy Mount).
    from ..skills.catalog import build_model_catalog
    from ..skills.catalog_service import SkillCatalogService

    configured = tuple(thread.spec.skills) + tuple(skill_roots)
    service = SkillCatalogService(
        project_path=thread.spec.project_path,
        cwd=thread.spec.project_path or Path.cwd(),
        configured_roots=configured,
        user_home=None,
        builtin_roots=builtin_roots,
    )
    catalog = service.reload()
    skills = catalog.registry  # legacy facade; new code consumes candidates

    capabilities = _run_capabilities(thread.spec)
    if catalog.candidates:
        combined_tools.append(
            _activation_use_skill_tool(catalog, sandbox, capabilities=capabilities)
        )

    system_tail = thread.spec.system or extra_system or agent_system
    budget = build_model_catalog(catalog)
    skills_prompt = _render_skills_prompt(budget, catalog)

    # SSH execution context (informational, between computer desc and skills)
    ssh_context = ""
    ssh_context_files = (
        getattr(getattr(sandbox, "spec", None), "ssh_context_files", ()) or ()
    )
    if sandbox is not None and ssh_context_files:
        docs = getattr(sandbox.backend, "execution_documents", ()) or ()
        if docs:
            from electromind.execution.context import build_ssh_context_prompt

            ssh_context = build_ssh_context_prompt(docs)

    system_prompt = "\n".join(
        part
        for part in (computer_desc, ssh_context, skills_prompt, system_tail)
        if part
    )

    if run_state is not None:
        run_state.phase = "idle"
    return RunResources(
        sandbox,
        skills,
        system_prompt,
        combined_tools,
        catalog_service=service,
        catalog=catalog,
    )


def build_context_manager(spec: ThreadSpec):
    """P0-2: 按 thread 模型构造生产 ContextManager（85% 预算门禁）。

    未注入时（旧路径）返回 None——正式 Runner 现在总是注入。
    """
    from ..context.manager import ContextManager
    from ..core.capabilities import resolve_model_capabilities

    model = getattr(spec, "model", "") or "deepseek-v4-flash"
    capabilities = resolve_model_capabilities(model)
    return ContextManager(capabilities)


def _with_context_manager(agent_kwargs: dict, spec: ThreadSpec) -> dict:
    """向 Agent 构造 kwargs 注入 context_manager（若未显式提供）。"""
    if "context_manager" not in agent_kwargs:
        agent_kwargs["context_manager"] = build_context_manager(spec)
    return agent_kwargs


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
        skill_runtime: SkillRuntime | None = None,
    ):
        super().__init__(agent, messages)
        self.thread = thread
        self.spec = thread.spec
        self.sandbox = sandbox
        self.skills = skills or SkillRegistry()
        self.skill_runtime = skill_runtime
        # R2-2: 注册门兜底 —— 覆盖 ChatRunner / 直接构造等未走
        # assemble_run_resources 的路径（补全内置 effect 后仍缺失即拒绝）。
        from ..execution.effects import apply_builtin_effects, assert_effects_declared

        resolved_tools = apply_builtin_effects(list(agent.tools or []))
        assert_effects_declared(resolved_tools)
        if resolved_tools != list(agent.tools or []):
            agent.replace_runtime_context(tools=resolved_tools)
        # R2-1: ContextManager 兜底注入（未显式注入的构造路径）
        if getattr(agent, "context_manager", None) is None:
            agent.context_manager = build_context_manager(thread.spec)

        self.store = store or thread.open_store()
        self.conversation_id = thread.messages_conversation_id
        self.messages = messages if messages is not None else thread.load_messages()

    async def before_user_turn(self, user_input: str) -> None:
        """Refresh the Skill catalog before every user turn.

        Phase-2: NO full install at generation change — skills mount lazily
        at activation time only (RFC section 九).  The view keeps its frozen
        catalog so ``apply_to_agent`` rebuilds the activation-backed tool
        (never a degraded empty legacy tool).
        """
        await super().before_user_turn(user_input)
        if self.skill_runtime is None:
            return

        view = self.skill_runtime.prepare_turn()
        if view is not None:
            self.skill_runtime.apply_to_agent(self.agent)

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
        max_turns: int = 24,
        skill_roots: Sequence[str | Path] = (),
        tools: Sequence[FunctionTool] = (),
        builtin_roots: Sequence[str | Path] | None = None,
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
            builtin_roots=builtin_roots,
        )

        # Phase-2: the runtime SHARES the catalog service used at assembly
        # time (same generation) and lazily mounts activated skills into the
        # sandbox — one discovery source, no double scanning.
        from ..skills.mounting import LazySkillMounter, SshLazySkillMounter
        from ..skills.snapstore import PrivateSnapshotStore

        _store = PrivateSnapshotStore()
        _mounter = None
        if resources.sandbox is not None:
            _backend = getattr(resources.sandbox, "backend", None)
            backend_name = getattr(getattr(_backend, "__class__", None), "__name__", "")
            if backend_name == "SshBackend":
                _mounter = SshLazySkillMounter(resources.sandbox, store=_store)
            else:
                _mounter = LazySkillMounter(resources.sandbox, store=_store)
        skill_runtime = SkillRuntime(
            thread.spec.project_path,
            configured_roots=tuple(thread.spec.skills) + tuple(skill_roots),
            mounter=_mounter,
            builtin_roots=builtin_roots,
            service=resources.catalog_service,
            capabilities=_run_capabilities(thread.spec),
        )
        # Pin generation 1 from the already-discovered catalog (same service
        # → same generation; reload() is a no-op on unchanged content).
        skill_runtime.prepare_turn()

        runner = cls(
            Agent(
                provider,
                system=resources.system_prompt,
                tools=resources.tools,
                max_turns=max_turns,
                **_with_context_manager({}, thread.spec),
            ),
            thread,
            sandbox=resources.sandbox,
            skills=resources.skills,
            skill_runtime=skill_runtime,
        )
        runner.run_state = run_state
        return runner


def _activation_use_skill_tool(
    catalog, sandbox, *, capabilities: Sequence[str] = ()
) -> FunctionTool:
    """Phase-2 ``use_skill`` tool backed by the activation service.

    Skills mount lazily at activation time (RFC 九): when a sandbox exists a
    mounter mounts the frozen snapshot into it; without one the tool still
    returns the frozen content from the private store.

    The mounter is selected by backend type — SSH environments use
    ``SshLazySkillMounter`` (full snapshot digest verification), local /
    container use ``LazySkillMounter``.  The Run capabilities are threaded
    into name resolution and the activation request so capability-restricted
    skills are enforced in production (not just in tests).
    """
    from ..skills.activation import (
        SkillActivationService,
        make_activation_use_skill_tool,
    )
    from ..skills.mounting import LazySkillMounter, SshLazySkillMounter
    from ..skills.snapstore import PrivateSnapshotStore

    store = PrivateSnapshotStore()
    mounter = None
    if sandbox is not None:
        _backend = getattr(sandbox, "backend", None)
        backend_name = getattr(getattr(_backend, "__class__", None), "__name__", "")
        if backend_name == "SshBackend":
            mounter = SshLazySkillMounter(sandbox, store=store)
        else:
            mounter = LazySkillMounter(sandbox, store=store)
    service = SkillActivationService(
        catalog,
        store=store,
        mounter=mounter,
        items_dir=store.root.parent / "activations",
        resolution=catalog.resolution,
    )
    return make_activation_use_skill_tool(
        service, thread_id="", run_id="", capabilities=capabilities
    )


def _run_capabilities(spec: ThreadSpec) -> tuple[str, ...]:
    """The Run capabilities derived from the execution target.

    The execution backend determines which skills may run: ``ssh`` grants the
    ``ssh`` capability, everything else grants ``local``.
    """
    backend = getattr(spec, "backend", None)
    if backend == "ssh":
        return ("ssh",)
    return ("local",)


def _render_skills_prompt(budget, catalog) -> str:
    """Render the skills section of the system prompt (candidate chain).

    Keeps the legacy marker contract (``<!-- electromind:skills:start -->``)
    and the ``use_skill`` hint; entries come from the model-visible budget.
    """
    from ..skills.runtime import SKILLS_END, SKILLS_START

    # A+ W5: no AGENTS.md global instructions — skills are self-contained;
    # per-skill rules live in each SKILL.md and its references.
    lines: list[str] = []
    lines.append(SKILLS_START)
    if budget.entries:
        lines.append("你可以按需加载这些 skill：")
        for entry in budget.entries:
            source = f" [{entry.source_label}]" if entry.source_label else ""
            if entry.description:
                lines.append(f"- `{entry.name}`{source}：{entry.description}")
            else:
                lines.append(f"- `{entry.name}`{source}")
        lines.append("调 `use_skill(name)` 会把对应 skill 的完整说明书加载进来。")
    else:
        lines.append("(暂无可用 skill)")
    lines.append(SKILLS_END)
    return "\n".join(lines) + "\n"

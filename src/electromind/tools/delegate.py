"""delegate —— 把一段子任务委派给一个命名子 agent。

范式：委派返回（不是控制权转移）。主 agent 调用 delegate 工具，Runner 压入一帧、
切到子 agent 的上下文跑完这段任务，再弹帧回到主 agent，把子 agent 的最终答复作为工具
结果交回。主 agent 全程不退出，delegate 对它就是一次普通的工具调用。

子 agent 与主 agent 同一个 Runner、同一个 thread：

- 对话：子 agent 用独立的 messages（空上下文起步），落盘到同一 thread 的 messages 目录，
  用命名空间 id ``<main>.sub.<name>.<seq>`` 与主对话区分。
- 沙箱：``sub_spec.workspace`` 为空则借用主 agent 的沙箱（同一地盘）；非空则在
  ``workspaces/<workspace>/`` 下开自己的沙箱，弹帧时关掉。``backend == "none"`` 不开沙箱。
- 归属：借来的资源弹帧时不关（``owned=False``），自己开的才关（``owned=True``）。

工具通过声明 ``context`` 形参拿到 Runner 句柄（见 `FunctionTool.wants_context`），
从而能在 Runner 的帧栈上压入 / 弹出子帧。
"""

from __future__ import annotations

import asyncio
import copy
import inspect
import json
from dataclasses import dataclass, field, replace

from ..core.agent import Agent
from ..core.budget import BudgetExceededError, RunBudget
from ..core.message import Messages, reply_text
from ..core.provider import ProviderProtocol
from ..core.tool import FunctionTool, ToolOutput, normalize_tool_output
from ..execution.effects import ToolEffect
from ..ithread import SubAgentSpec
from ..runtime.frame import RunFrame
from ..runtime.resource import ConversationResource, ResourceSlot
from ..runtime.run_state import RunState
from ..sandbox import Sandbox, open_sandbox_for_spec
from ..skills import SkillRegistry


def observe_subagent_event(context, name: str, event) -> None:
    """把子 agent 的内部事件交给可选观察者；未启用时静默跳过。

    这是给 desktop 实验用的旁路观察口，不改变主事件流语义：主 agent 侧仍只把
    delegate 视作一次普通工具调用。
    """
    observer = getattr(context, "observe_subagent_event", None)
    if not callable(observer):
        return
    observer(
        name=name,
        conversation_id=str(getattr(context, "conversation_id", "") or ""),
        event=event,
    )


# ── M5: 结构化结果与委派预算 ────────────────────────────────────────────

# 系统最大委派深度（硬限制，不可配置放宽）
SYSTEM_MAX_DEPTH = 2


@dataclass
class SubAgentResult:
    """子 agent 的结构化交付（M5 §10.1）。父 agent 不得只接收自由文本。"""

    status: str = "completed"  # completed | timeout | budget_exceeded | error | denied
    summary: str = ""
    artifacts: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    unresolved_questions: list[str] = field(default_factory=list)
    verification: list[str] = field(default_factory=list)
    usage: dict = field(default_factory=dict)  # tokens / tool_calls / model_calls

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "summary": self.summary,
            "artifacts": list(self.artifacts),
            "evidence": list(self.evidence),
            "assumptions": list(self.assumptions),
            "unresolved_questions": list(self.unresolved_questions),
            "verification": list(self.verification),
            "usage": dict(self.usage),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


def delegation_depth(context) -> int:
    """当前委派深度 = 帧栈中除基帧外的帧数。"""
    return max(0, len(getattr(context, "frames", [])) - 1)


def check_delegation_allowed(context, sub_spec: SubAgentSpec, name: str) -> str | None:
    """委派前置检查：返回拒绝原因；None = 允许。

    - 深度：``min(sub_spec.max_depth, SYSTEM_MAX_DEPTH)`` 硬限制。
    - 循环委派：系统最大深度 2 保证主→子→孙 后必然拒绝。
    """
    depth = delegation_depth(context)
    limit = min(sub_spec.max_depth, SYSTEM_MAX_DEPTH)
    if depth + 1 > limit:
        return (
            f"子 agent {name!r} 委派深度超限：当前 {depth}，上限 {limit}"
            f"（系统最大 {SYSTEM_MAX_DEPTH}，禁止无限委派）"
        )
    return None


def filter_tools_by_whitelist(
    tools: list[FunctionTool], allowed: tuple[str, ...] | list[str]
) -> list[FunctionTool]:
    """按工具白名单过滤；白名单为空 = 放开全部。"""
    if not allowed:
        return list(tools)
    names = set(allowed)
    return [t for t in tools if t.name in names]


def bound_paths(
    tools: list[FunctionTool],
    *,
    read_paths: tuple[str, ...] = (),
    write_paths: tuple[str, ...] = (),
) -> list[FunctionTool]:
    """按读写路径边界包裹工具；边界为空 = 不限制。

    包裹层检查 ``path`` 参数是否在允许前缀内，越界返回失败 ToolOutput。
    """
    if not read_paths and not write_paths:
        return list(tools)

    read_prefixes = tuple(p.rstrip("/") + "/" for p in read_paths)
    write_prefixes = tuple(p.rstrip("/") + "/" for p in write_paths)

    def _within(prefixes: tuple[str, ...], path: str) -> bool:
        """规范化后判定：``data/../../secret`` 归一到 ../secret → 拒绝；
        绝对路径或上级引用一律拒绝（P0-6 路径穿越修复）。"""
        import posixpath

        normalized = posixpath.normpath(str(path))
        if normalized.startswith("../") or normalized == "..":
            return False
        if normalized.startswith("/"):
            return False
        return any(
            normalized == p.rstrip("/") or normalized.startswith(p) for p in prefixes
        )

    def wrap(tool: FunctionTool) -> FunctionTool:
        orig = tool.func

        async def guarded(*args, **kwargs) -> ToolOutput:
            path = kwargs.get("path") or (args[0] if args else "")
            if isinstance(path, str):
                if (
                    tool.name.startswith("read")
                    and read_prefixes
                    and not _within(read_prefixes, path)
                ):
                    return ToolOutput.fail(
                        f"子 agent 路径越界：读取 {path!r} 不在允许目录 {read_paths} 内"
                    )
                if (
                    tool.name.startswith("write")
                    and write_prefixes
                    and not _within(write_prefixes, path)
                ):
                    return ToolOutput.fail(
                        f"子 agent 路径越界：写入 {path!r} 不在允许目录 {write_paths} 内"
                    )
            if inspect.iscoroutinefunction(orig):
                return await orig(*args, **kwargs)
            result = orig(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
            return normalize_tool_output(result)

        return FunctionTool(
            name=tool.name,
            description=tool.description,
            parameters=tool.parameters,
            func=guarded,
            effect=tool.effect,
        )

    return [
        wrap(t) if t.name.startswith(("read_", "write_", "str_")) else t for t in tools
    ]


def provider_with_model(provider: ProviderProtocol, model: str) -> ProviderProtocol:
    """按子 agent 指定的 model 派生 provider；未指定或 provider 无 model_id 则原样复用。

    Provider 的 client 可共享，只换 ``model_id``，浅拷贝即可。
    """
    if not model or getattr(provider, "model_id", None) is None:
        return provider
    clone = copy.copy(provider)
    clone.model_id = model
    return clone


async def open_sub_sandbox(
    thread, sub_spec: SubAgentSpec, parent_sandbox: Sandbox | None
) -> tuple[Sandbox | None, bool]:
    """按 sub_spec 决定子 agent 的沙箱；返回 (sandbox, owned)。

    - ``backend``（含继承主 thread 的值）为 ``none``：不开沙箱。
    - 未指定 ``workspace``：借用主 agent 的沙箱（``owned=False``），同一地盘协作。
    - 指定 ``workspace``：在 ``workspaces/<workspace>/`` 下开自己的沙箱（``owned=True``），
      backend / sandbox_tools 用 sub_spec 覆盖，缺省继承主 thread。
    """
    resolved_backend = sub_spec.backend or thread.spec.backend
    if resolved_backend == "none":
        return None, False

    if not sub_spec.workspace:
        return parent_sandbox, False

    workspace = thread.workspace_path_for(sub_spec.workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    profile = replace(
        thread.spec,
        backend=resolved_backend,
        sandbox_tools=sub_spec.sandbox_tools or thread.spec.sandbox_tools,
    )
    sandbox = await open_sandbox_for_spec(
        profile,
        str(workspace),
        label=f"thread {thread.id!r} sub {sub_spec.workspace!r}",
    )
    return sandbox, True


def next_sub_conversation_id(store, main_id: str, name: str) -> str:
    """在同一 thread 的 store 里为子对话取一个不冲突的命名空间 id。

    形如 ``<main>.sub.<name>.<seq>``，seq 按该 (main, name) 已有的子对话数递增。
    """
    prefix = f"{main_id}.sub.{name}."
    existing = [cid for cid in store.list() if cid.startswith(prefix)]
    return f"{prefix}{len(existing)}"


async def build_sub_frame(context, name: str, sub_spec: SubAgentSpec) -> RunFrame:
    """在当前 Runner 上装配一帧子 agent 上下文（尚未压栈）。"""
    thread = context.thread
    store = context.store
    parent_sandbox = context.sandbox

    sandbox, owns_sandbox = await open_sub_sandbox(thread, sub_spec, parent_sandbox)

    computer_desc = await sandbox.describe() if sandbox is not None else ""
    system_prompt = "\n".join(part for part in (computer_desc, sub_spec.system) if part)
    tools = sandbox.tools() if sandbox is not None else []
    # M5：工具白名单 + 读写路径边界
    tools = filter_tools_by_whitelist(tools, sub_spec.allowed_tools)
    tools = bound_paths(
        tools,
        read_paths=sub_spec.read_paths,
        write_paths=sub_spec.write_paths,
    )

    provider = provider_with_model(context.agent.provider, sub_spec.model)
    budget = (
        RunBudget(max_total_tokens=sub_spec.max_tokens)
        if sub_spec.max_tokens > 0
        else None
    )
    sub_agent = Agent(
        provider,
        system=system_prompt,
        tools=tools,
        max_turns=sub_spec.max_turns,
        budget=budget,
    )

    conversation_id = next_sub_conversation_id(
        store, thread.messages_conversation_id, name
    )

    slots = [ResourceSlot(ConversationResource(store), owned=False)]
    if sandbox is not None:
        slots.append(ResourceSlot(sandbox, owned=owns_sandbox))

    return RunFrame(
        agent=sub_agent,
        messages=Messages(),
        conversation_id=conversation_id,
        run_state=RunState(),
        sandbox=sandbox,
        store=store,
        skills=SkillRegistry(),
        slots=slots,
        # P0-6: 帧级工具预算（执行前硬限）
        max_tool_calls=sub_spec.max_tool_calls,
    )


async def run_sub_agent(
    context, name: str, task: str, sub_spec: SubAgentSpec
) -> SubAgentResult:
    """在当前栈顶帧（子帧）上把 task 跑到结束，返回结构化结果。

    复用 Runner 自己的 ``run``：它读写的 ``agent`` / ``messages`` / ``store`` 等都经
    property 指向栈顶帧，因而落到子帧上——包括子对话的落盘。默认仍在此处丢弃事件，
    只取结果；若 runner 安装了观察者，会旁路上报给前端实验展示。

    M5 契约：
    - 超时（``timeout_seconds``）→ status=timeout 的结构化终止。
    - token 预算（``max_tokens``，经 Agent.budget 硬检查）→ status=budget_exceeded。
    - 工具调用数（``max_tool_calls``）在结束后检查 → 超限标记 budget_exceeded。
    """
    usage: dict = {}
    status = "completed"
    timeout = sub_spec.timeout_seconds
    try:
        if timeout and timeout > 0:

            async def _run():
                async for event in context.run(task):
                    observe_subagent_event(context, name, event)

            await asyncio.wait_for(_run(), timeout=timeout)
        else:
            async for event in context.run(task):
                observe_subagent_event(context, name, event)
    except asyncio.TimeoutError:
        status = "timeout"
    except BudgetExceededError:
        status = "budget_exceeded"
    except Exception as exc:  # noqa: BLE001 — 结构化终止，不吞错误详情
        status = "error"
        usage["error"] = f"{type(exc).__name__}: {exc}"[:200]

    messages = context.messages.data
    summary = reply_text(messages)
    tool_calls = _count_tool_calls(messages)
    last_usage = getattr(context.agent, "last_usage", None)
    if last_usage:
        usage["tokens"] = last_usage
    usage["tool_calls"] = tool_calls
    usage["model_calls"] = getattr(
        getattr(context.agent, "budget", None), "model_calls", 0
    )
    if status == "completed" and sub_spec.max_tool_calls > 0:
        if tool_calls > sub_spec.max_tool_calls:
            status = "budget_exceeded"
    if status != "completed":
        summary = summary or f"子 agent {name!r} 未完成（{status}）"
    return SubAgentResult(
        status=status,
        summary=summary,
        artifacts=[
            getattr(getattr(m, "content", None), "tool_call_id", "")
            for m in messages
            if m.role == "assistant"
        ],
        evidence=[],
        assumptions=[],
        unresolved_questions=[],
        verification=[],
        usage=usage,
    )


def _count_tool_calls(messages) -> int:
    count = 0
    for m in messages:
        content = getattr(m, "content", None)
        if m.role == "assistant" and getattr(content, "type", "") == "function":
            count += 1
    return count


def make_delegate_tool(
    name: str,
    sub_spec: SubAgentSpec,
    *,
    tool_name: str | None = None,
    description: str | None = None,
) -> FunctionTool:
    """产出一个把任务委派给命名子 agent ``name`` 的工具。

    闭包捕获子 agent 的名字与 spec；调用时在 Runner 帧栈上压入子帧、跑完、弹帧，把子
    agent 的最终答复作为工具结果返回。

    Args:
        name: 子 agent 名（对应 thread.toml 的 ``[sub.<name>]``），用于命名子对话。
        sub_spec: 子 agent 配置。
        tool_name: 工具名，默认 ``delegate_to_<name>``。
        description: 工具描述，默认据 name / sub_spec 生成。
    """

    async def delegate(task: str, context=None) -> ToolOutput:
        if context is None or not hasattr(context, "push_frame"):
            return ToolOutput.fail("delegate 需要运行在支持帧栈的 Runner 上")
        if getattr(context, "thread", None) is None:
            return ToolOutput.fail("delegate 需要绑定 thread 的 Runner")
        denied = check_delegation_allowed(context, sub_spec, name)
        if denied is not None:
            return ToolOutput.fail(denied)

        frame = await build_sub_frame(context, name, sub_spec)
        context.push_frame(frame)
        try:
            result = await run_sub_agent(context, name, task, sub_spec)
        finally:
            await context.pop_frame()
        return ToolOutput.succeed(result.to_json())

    resolved_name = tool_name or f"delegate_to_{name}"
    resolved_desc = description or (
        f"把一段子任务交给子 agent `{name}` 独立完成，并拿回它的最终答复。"
        "子 agent 有自己的对话上下文，适合把可隔离的子任务打包出去。"
    )
    return FunctionTool(
        name=resolved_name,
        description=resolved_desc,
        parameters={
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": f"交给子 agent `{name}` 的任务描述。",
                },
            },
            "required": ["task"],
            "additionalProperties": False,
        },
        func=delegate,
        effect=ToolEffect.EXECUTE,
    )


def make_delegate_tools(subs: dict[str, SubAgentSpec]) -> list[FunctionTool]:
    """为一组命名子 agent 各产出一个 delegate 工具。

    通常传 ``thread.spec.subs``，把 thread.toml 里声明的子 agent 全部挂成工具。
    """
    return [make_delegate_tool(name, spec) for name, spec in subs.items()]


SUBAGENT_TOOL_NAME = "delegate_to_subagent"


def make_subagent_tool(subs: dict[str, SubAgentSpec]) -> FunctionTool:
    """产出统一的 ``delegate_to_subagent`` 工具：一个工具按 ``type`` 委派给某个子 agent。

    与 ``make_delegate_tools``（一个子 agent 一个工具名）相对，这里所有子 agent 共用
    一个工具，``type`` 用 JSON schema 的 ``enum`` 约束为已配置的子 agent 名。主流程用
    这个，thread.toml 的 ``[agent] tools`` 列出 ``delegate_to_subagent`` 才挂载。

    Args:
        subs: 命名子 agent 表，通常是 ``thread.spec.subs``。
    """
    names = list(subs)

    async def delegate(type: str, task: str, context=None) -> ToolOutput:
        if context is None or not hasattr(context, "push_frame"):
            return ToolOutput.fail("delegate 需要运行在支持帧栈的 Runner 上")
        if getattr(context, "thread", None) is None:
            return ToolOutput.fail("delegate 需要绑定 thread 的 Runner")
        sub_spec = subs.get(type)
        if sub_spec is None:
            available = ", ".join(names) or "（无）"
            return ToolOutput.fail(f"未知子 agent type={type!r}；可用：{available}")
        denied = check_delegation_allowed(context, sub_spec, type)
        if denied is not None:
            return ToolOutput.fail(denied)

        frame = await build_sub_frame(context, type, sub_spec)
        context.push_frame(frame)
        try:
            result = await run_sub_agent(context, type, task, sub_spec)
        finally:
            await context.pop_frame()
        return ToolOutput.succeed(result.to_json())

    catalog = "\n".join(
        f"- {name}: {(spec.system or '').strip() or '（无描述）'}"
        for name, spec in subs.items()
    )
    return FunctionTool(
        name=SUBAGENT_TOOL_NAME,
        description=(
            "把一段可隔离的子任务委派给一个子 agent 独立完成，并拿回它的最终答复。"
            "子 agent 有自己的对话上下文。按 type 选择子 agent，可用：\n" + catalog
        ),
        effect=ToolEffect.EXECUTE,
        parameters={
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": names,
                    "description": "要委派给哪个子 agent（取值为已配置的子 agent 名）。",
                },
                "task": {
                    "type": "string",
                    "description": "交给子 agent 的任务描述。",
                },
            },
            "required": ["type", "task"],
            "additionalProperties": False,
        },
        func=delegate,
    )

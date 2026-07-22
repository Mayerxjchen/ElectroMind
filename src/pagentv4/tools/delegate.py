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

import copy
from dataclasses import replace

from ..core.agent import Agent
from ..core.message import Messages, reply_text
from ..core.provider import ProviderProtocol
from ..core.tool import FunctionTool, ToolOutput
from ..ithread import SubAgentSpec
from ..runtime.frame import RunFrame
from ..runtime.resource import ConversationResource, ResourceSlot
from ..runtime.run_state import RunState
from ..sandbox import Sandbox, open_sandbox_for_spec
from ..skills import SkillRegistry


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

    provider = provider_with_model(context.agent.provider, sub_spec.model)
    sub_agent = Agent(
        provider,
        system=system_prompt,
        tools=tools,
        max_turns=sub_spec.max_turns,
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
    )


async def run_sub_agent(context, task: str) -> str:
    """在当前栈顶帧（子帧）上把 task 跑到结束，返回子 agent 的最终文本答复。

    复用 Runner 自己的 ``run``：它读写的 ``agent`` / ``messages`` / ``store`` 等都经
    property 指向栈顶帧，因而落到子帧上——包括子对话的落盘。事件在此处丢弃，只取结果。
    """
    async for _ in context.run(task):
        pass
    return reply_text(context.messages.data)


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

        frame = await build_sub_frame(context, name, sub_spec)
        context.push_frame(frame)
        try:
            answer = await run_sub_agent(context, task)
        finally:
            await context.pop_frame()
        return ToolOutput.succeed(answer or f"子 agent {name!r} 未产出文本答复")

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
    )


def make_delegate_tools(subs: dict[str, SubAgentSpec]) -> list[FunctionTool]:
    """为一组命名子 agent 各产出一个 delegate 工具。

    通常传 ``thread.spec.subs``，把 thread.toml 里声明的子 agent 全部挂成工具。
    """
    return [make_delegate_tool(name, spec) for name, spec in subs.items()]

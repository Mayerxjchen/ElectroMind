from __future__ import annotations

from ..core.agent import Agent
from ..core.message import Message, Messages
from ..core.tool import ToolOutput
from ..core.turn_result import TurnResult
from ..runtime.runner import append_message, ensure_system


async def execute_tool(agent: Agent, tool_call: dict) -> ToolOutput:
    function_call = tool_call["function"]
    name = function_call["name"]
    tool = agent.tool_map.get(name)
    if tool is None:
        return ToolOutput.fail(
            f"error: unknown tool {name!r}; available: {sorted(agent.tool_map)}"
        )
    return await tool.acall(function_call["arguments"])


async def run_agent(
    agent: Agent,
    prompt: str,
    *,
    messages: Messages | None = None,
    run_kwargs: dict | None = None,
) -> str:
    """无沙箱：一次 prompt 跑完 tool loop，返回最终文本。"""
    run_kwargs = run_kwargs or {}
    messages = messages or Messages()
    ensure_system(messages, agent.system)
    turn_id = messages.max_turn_id() + 1
    append_message(messages, Message.user(prompt), turn_id=turn_id)

    for turn in range(agent.max_turns):
        turn_start = len(messages.data)

        async for message in agent.stream_messages(messages, **run_kwargs):
            append_message(messages, message, turn_id=turn_id)

        result = TurnResult.from_slice(messages.data, turn_start)

        if turn_start >= len(messages.data):
            return ""

        if not result.has_tool_calls:
            return result.content

        for tool_call in result.tool_calls:
            output = await execute_tool(agent, tool_call)
            append_message(
                messages,
                Message.tool_result(tool_call["id"], output.content),
                turn_id=turn_id,
            )

        if turn + 1 >= agent.max_turns:
            tail = TurnResult.from_slice(messages.data, turn_start)
            return tail.content

    raise RuntimeError("unreachable")

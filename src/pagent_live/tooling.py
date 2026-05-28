"""Tool helpers for :mod:`pagent_live` (``context`` injection without changing ``pagent.tool``)."""

import inspect
import json

from pagent.tool import ToolOutput, normalize_tool_output

from .context import ToolContext

CONTEXT_PARAM = "context"


def declares_context(func) -> bool:
    return CONTEXT_PARAM in inspect.signature(func).parameters


def call_with_context(function_tool, arguments, agent, tool_call_id: str) -> ToolOutput:
    if function_tool.func is None:
        return ToolOutput.fail(f"tool {function_tool.name} has no bound function")

    ctx = ToolContext(agent=agent, tool_call_id=tool_call_id)
    with_context = declares_context(function_tool.func)

    def invoke(kwargs):
        if with_context:
            kwargs = {**kwargs, CONTEXT_PARAM: ctx}
        return normalize_tool_output(function_tool.func(**kwargs))

    try:
        if arguments is None:
            return invoke({})

        if isinstance(arguments, str):
            stripped = arguments.strip()
            if not stripped:
                return invoke({})
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as e:
                return ToolOutput.fail(f"Invalid JSON in tool arguments: {e}")
            return invoke(payload)

        return invoke(dict(arguments))
    except Exception as e:
        return ToolOutput.fail(f"{function_tool.name} error: {e}")


async def call_with_context_async(
    function_tool, arguments, agent, tool_call_id: str
) -> ToolOutput:
    if function_tool.func is None:
        return ToolOutput.fail(f"tool {function_tool.name} has no bound function")

    ctx = ToolContext(agent=agent, tool_call_id=tool_call_id)
    with_context = declares_context(function_tool.func)

    async def invoke(kwargs):
        if with_context:
            kwargs = {**kwargs, CONTEXT_PARAM: ctx}
        result = function_tool.func(**kwargs)
        if inspect.isawaitable(result):
            result = await result
        return normalize_tool_output(result)

    try:
        if arguments is None:
            return await invoke({})

        if isinstance(arguments, str):
            stripped = arguments.strip()
            if not stripped:
                return await invoke({})
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as e:
                return ToolOutput.fail(f"Invalid JSON in tool arguments: {e}")
            return await invoke(payload)

        return await invoke(dict(arguments))
    except Exception as e:
        return ToolOutput.fail(f"{function_tool.name} error: {e}")

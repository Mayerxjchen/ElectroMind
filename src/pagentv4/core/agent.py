from collections.abc import AsyncIterator

from .message import Message, Messages, ToolCall
from .provider import ProviderProtocol
from .tool import FunctionTool, to_openai_tools


class AgentCore:
    def __init__(
        self,
        provider: ProviderProtocol,
        *,
        system: str | None = None,
        tools: list[FunctionTool] | None = None,
        max_turns: int = 8,
    ):
        self.provider = provider
        self.system = system

        self.tools = tools or []
        self.tool_schemas = to_openai_tools(self.tools) or None
        names = [tool.name for tool in self.tools]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate tool names: {names}")
        self.tool_map: dict[str, FunctionTool] = {
            tool.name: tool for tool in self.tools
        }

        if max_turns < 1:
            raise ValueError("max_turns must be >= 1")
        self.max_turns = max_turns

    async def generate_messages(
        self,
        messages: Messages,
        **run_kwargs,
    ) -> AsyncIterator[Message]:
        stream = await self.provider.complete(
            messages.to_openai(),
            tools=self.tool_schemas,
            **run_kwargs,
        )
        tool_calls_by_idx: dict[int, dict] = {}

        async for chunk in stream:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue

            delta = getattr(choices[0], "delta", None)
            if delta is None:
                continue

            content = getattr(delta, "content", None)
            if content:
                yield Message.assistant({"type": "text", "text": content})

            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                yield Message.assistant({"type": "thinking", "text": reasoning})

            for tool_call_delta in getattr(delta, "tool_calls", None) or []:
                index = getattr(tool_call_delta, "index", 0)
                tool_call = tool_calls_by_idx.setdefault(
                    index,
                    {
                        "id": "",
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    },
                )
                tool_call_id = getattr(tool_call_delta, "id", None)
                if tool_call_id:
                    tool_call["id"] = tool_call_id
                tool_call_type = getattr(tool_call_delta, "type", None)
                if tool_call_type:
                    tool_call["type"] = tool_call_type

                function_delta = getattr(tool_call_delta, "function", None)
                if function_delta is None:
                    continue

                function_name = getattr(function_delta, "name", None)
                if function_name:
                    tool_call["function"]["name"] += function_name
                function_arguments = getattr(function_delta, "arguments", None)
                if function_arguments:
                    tool_call["function"]["arguments"] += function_arguments

        for _, tool_call in sorted(tool_calls_by_idx.items()):
            yield Message(role="assistant", content=ToolCall.from_openai(tool_call))


Agent = AgentCore

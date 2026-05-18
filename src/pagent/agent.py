from collections.abc import AsyncIterator

from .llm import RunResult
from .tool import to_openai_tools


class AgentStats:
    def __init__(self):
        self.usage = None
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.turns = 0

    def add_usage(self, usage):
        self.usage = usage
        self.turns += 1
        if usage:
            self.prompt_tokens += usage.prompt_tokens
            self.completion_tokens += usage.completion_tokens
            self.total_tokens += usage.total_tokens

    def __str__(self):
        return (
            f"turns={self.turns}, "
            f"prompt_tokens={self.prompt_tokens}, "
            f"completion_tokens={self.completion_tokens}, "
            f"total_tokens={self.total_tokens}"
        )


class Agent:
    def __init__(self, llm, session, tools=None, max_turns=8):
        self.llm = llm
        self.session = session
        self.tools = tools or []
        self.tool_schemas = to_openai_tools(self.tools)
        names = [t.name for t in self.tools]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate tool names: {names}")
        self.tool_map = {t.name: t for t in self.tools}
        if max_turns < 1:
            raise ValueError("max_turns must be >= 1")
        self.max_turns = max_turns
        self.stats = AgentStats()

    def _execute_tool_calls(self, tool_calls):
        for tool_call in tool_calls:
            function_call = tool_call["function"]
            name = function_call["name"]
            tc = self.tool_map.get(name)
            self.session += {
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": (
                    f"error: unknown tool {name!r}; available: {sorted(self.tool_map)}"
                    if tc is None
                    else tc.call(function_call["arguments"])
                ),
            }

    def reset(self):
        self.session.reset()
        self.stats = AgentStats()

    def _assistant_message(self, result):
        message = {"role": "assistant", "content": result.content or None}
        if result.tool_calls:
            message["tool_calls"] = result.tool_calls
        if result.reasoning_content:
            message["reasoning_content"] = result.reasoning_content
        return message

    async def _invoke_stream_once(self) -> AsyncIterator[str]:
        content_parts = []
        reasoning_content_parts = []
        tool_calls_by_idx = {}
        usage = None

        async for chunk in self.llm.invoke_stream(
            self.session.messages, tools=self.tool_schemas
        ):
            usage = getattr(chunk, "usage", usage)
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue

            delta = getattr(choices[0], "delta", None)
            if delta is None:
                continue

            content = getattr(delta, "content", None)
            if content:
                content_parts.append(content)
                yield content
            reasoning_content = getattr(delta, "reasoning_content", None)
            if reasoning_content:
                reasoning_content_parts.append(reasoning_content)

            for tc_delta in getattr(delta, "tool_calls", None) or []:
                idx = getattr(tc_delta, "index", 0)
                tc = tool_calls_by_idx.setdefault(
                    idx,
                    {
                        "id": "",
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    },
                )
                tc_id = getattr(tc_delta, "id", None)
                if tc_id:
                    tc["id"] = tc_id
                tc_type = getattr(tc_delta, "type", None)
                if tc_type:
                    tc["type"] = tc_type

                fn_delta = getattr(tc_delta, "function", None)
                if fn_delta is None:
                    continue

                fn_name = getattr(fn_delta, "name", None)
                if fn_name:
                    tc["function"]["name"] += fn_name
                fn_args = getattr(fn_delta, "arguments", None)
                if fn_args:
                    tc["function"]["arguments"] += fn_args

        tool_calls = [
            tc for _, tc in sorted(tool_calls_by_idx.items(), key=lambda item: item[0])
        ]
        result = RunResult(
            content="".join(content_parts),
            tool_calls=tool_calls,
            reasoning_content="".join(reasoning_content_parts),
            usage=usage,
        )
        self.session += self._assistant_message(result)
        self.stats.add_usage(result.usage)

        if result.has_tool_calls:
            self._execute_tool_calls(result.tool_calls)

    async def run(self, user_input):
        self.session += {"role": "user", "content": user_input}
        result = RunResult(content="")

        for _ in range(self.max_turns):
            result = await self.llm.invoke(
                self.session.messages, tools=self.tool_schemas
            )
            self.session += self._assistant_message(result)
            self.stats.add_usage(result.usage)

            if not result.has_tool_calls:
                return result

            self._execute_tool_calls(result.tool_calls)

        return result

    async def arun(self, user_input):
        self.session += {"role": "user", "content": user_input}
        for _ in range(self.max_turns):
            turn_start = len(self.session.messages)
            async for content in self._invoke_stream_once():
                yield content

            if turn_start >= len(self.session.messages):
                return
            assistant_message = self.session.messages[turn_start]
            if not assistant_message.get("tool_calls"):
                return

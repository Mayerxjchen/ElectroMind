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
            if tc is None:
                self.session += {
                    "role": "tool",
                    "content": f"error: unknown tool {name!r}; available: {sorted(self.tool_map)}",
                    "tool_call_id": tool_call["id"],
                }
                continue
            tool_result = tc.call(function_call["arguments"])
            self.session += {
                "role": "tool",
                "content": tool_result,
                "tool_call_id": tool_call["id"],
            }

    def reset(self):
        self.session.reset()
        self.stats = AgentStats()

    async def run(self, user_input):
        self.session += {"role": "user", "content": user_input}
        result = RunResult(content="")

        for _ in range(self.max_turns):
            result = await self.llm.invoke(
                self.session.messages, tools=self.tool_schemas
            )
            if result.tool_calls:
                self.session += {
                    "role": "assistant",
                    "content": result.content or None,
                    "tool_calls": result.tool_calls,
                }
            else:
                self.session += {"role": "assistant", "content": result.content}
            self.stats.add_usage(result.usage)

            if not result.has_tool_calls:
                return result

            self._execute_tool_calls(result.tool_calls)

        return result

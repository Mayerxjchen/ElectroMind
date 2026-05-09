from dataclasses import dataclass

from .llm import LLM, RunResult
from .session import Session
from .tool import FunctionTool, to_openai_tools


@dataclass
class AgentStats:
    usage: object | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    turns: int = 0
    max_turns_reached: bool = False

    def add_usage(self, usage: object | None) -> None:
        self.usage = usage
        self.turns += 1
        if usage:
            self.prompt_tokens += usage.prompt_tokens
            self.completion_tokens += usage.completion_tokens
            self.total_tokens += usage.total_tokens

    def __str__(self) -> str:
        return (
            f"turns={self.turns}, "
            f"prompt_tokens={self.prompt_tokens}, "
            f"completion_tokens={self.completion_tokens}, "
            f"total_tokens={self.total_tokens}, "
            f"max_turns_reached={self.max_turns_reached}"
        )


class Agent:
    def __init__(
        self,
        llm: LLM,
        session: Session,
        tools: list[FunctionTool] | None = None,
        max_turns: int = 8,
    ) -> None:
        self.llm = llm
        self.session = session
        self.tools: list[FunctionTool] = tools or []
        self.tool_schemas: list[dict] = to_openai_tools(self.tools)
        names = [t.name for t in self.tools]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate tool names: {names}")
        self.tool_map: dict[str, FunctionTool] = {t.name: t for t in self.tools}
        if max_turns < 1:
            raise ValueError("max_turns must be >= 1")
        self.max_turns = max_turns
        self.stats = AgentStats()

    def _execute_tool_calls(self, tool_calls: list[dict]) -> None:
        for tool_call in tool_calls:
            function_call = tool_call["function"]
            name = function_call["name"]
            tc = self.tool_map.get(name)
            if tc is None:
                self.session.add_tool(
                    f"error: unknown tool {name!r}; available: {sorted(self.tool_map)}",
                    tool_call_id=tool_call["id"],
                )
                continue
            tool_result: str = tc.call(function_call["arguments"])
            self.session.add_tool(tool_result, tool_call_id=tool_call["id"])

    def reset(self) -> None:
        self.session.reset()
        self.stats = AgentStats()

    async def run(self, user_input: str) -> RunResult:
        self.session.add_user(user_input)
        result = RunResult(content="")
        self.stats.max_turns_reached = False

        llm_calls = 0
        call_limit = self.max_turns
        while llm_calls < call_limit:
            result = await self.llm.invoke(
                self.session.get_messages(), tools=self.tool_schemas
            )
            llm_calls += 1
            self.session.add_assistant(result.content, tool_calls=result.tool_calls)
            self.stats.add_usage(result.usage)

            if not result.has_tool_calls:
                return result

            self._execute_tool_calls(result.tool_calls)

            if llm_calls == self.max_turns:
                self.stats.max_turns_reached = True
                call_limit = self.max_turns * 2

        return result

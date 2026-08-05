from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from ..context.manager import ContextInput
from .message import Message, Messages, ToolCall
from .provider import ProviderProtocol
from .tool import FunctionTool, to_openai_tools
from .usage import usage_to_dict


class ContextLimitError(RuntimeError):
    """上下文预算硬门禁：压缩后仍超限，模型调用被拒绝（fail-closed）。"""


if TYPE_CHECKING:
    from ..context.manager import ContextManager
    from .budget import RunBudget
    from .capabilities import ModelCapabilities
    from .retry import RetryPolicy


class AgentCore:
    def __init__(
        self,
        provider: ProviderProtocol,
        *,
        system: str | None = None,
        tools: list[FunctionTool] | None = None,
        max_turns: int = 24,
        budget: "RunBudget | None" = None,
        retry_policy: "RetryPolicy | None" = None,
        capabilities: "ModelCapabilities | None" = None,
        context_manager: "ContextManager | None" = None,
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
        self.last_usage: dict | None = None
        self.last_retry: dict | None = None
        # M7：预算 / 重试 / 能力（可选注入，未注入时行为与旧版一致）
        self.budget = budget
        self.retry_policy = retry_policy
        self.capabilities = capabilities
        # M3：上下文构造器（可选注入；未注入时直发完整历史，与旧版一致）
        self.context_manager = context_manager
        self.last_context_budget = None

    def replace_runtime_context(
        self,
        *,
        system: str | None = None,
        tools: list[FunctionTool] | None = None,
    ) -> None:
        """Atomically replace the system prompt and/or tools.

        All replacement values are built before assigning, so a validation
        failure leaves the old values intact.

        Raises:
            ValueError: if *tools* contains duplicate names.
        """
        new_tools = tools if tools is not None else self.tools
        schemas = to_openai_tools(new_tools) or None
        names = [tool.name for tool in new_tools]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate tool names: {names}")
        tool_map = {tool.name: tool for tool in new_tools}

        if system is not None:
            self.system = system
        self.tools = new_tools
        self.tool_schemas = schemas
        self.tool_map = tool_map

    async def generate_messages(
        self,
        messages: Messages,
        **run_kwargs,
    ) -> AsyncIterator[Message]:
        if self.budget is not None:
            self.budget.check()  # 超预算 → BudgetExceededError（结构化终止）

        # M3：上下文构造（预算检查 + 压缩）在发送前完成。
        # 预算 ok 时原样发送（消息零变化）；超阈值才用压缩后的消息。
        outbound = messages.to_openai()
        if self.context_manager is not None:
            prepared = self.context_manager.prepare(
                ContextInput(
                    system=self.system or "",
                    recent_messages=outbound,
                    pinned_constraints=(
                        self.context_manager.compactor.pinned_constraints
                    ),
                )
            )
            if prepared.budget.decision == "limit":
                # R2-1 硬门禁：压缩后仍超限 → 拒绝调用 Provider（fail-closed）
                raise ContextLimitError(
                    f"上下文超限：estimate={prepared.budget.estimate} "
                    f"threshold={prepared.budget.threshold} "
                    f"window={prepared.budget.window}；压缩后仍无法满足"
                )
            if prepared.budget.decision != "ok":
                outbound = prepared.messages
            self.last_context_budget = prepared.budget

        if self.retry_policy is not None:
            from .retry import run_with_retry

            def _open():
                return self.provider.complete(
                    outbound,
                    tools=self.tool_schemas,
                    **run_kwargs,
                )

            stream, _ = await run_with_retry(
                _open, policy=self.retry_policy, on_retry=self._on_provider_retry
            )
        else:
            stream = await self.provider.complete(
                outbound,
                tools=self.tool_schemas,
                **run_kwargs,
            )

        tool_calls_by_idx: dict[int, dict] = {}
        self.last_usage = None

        async for chunk in stream:
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage is not None:
                self.last_usage = usage_to_dict(chunk_usage)

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

        # M7：模型调用后记账（含未知 usage 的保守估算路径由调用方决定）
        if self.budget is not None:
            self.budget.account_model_call(self.last_usage, conservative=False)

    def _on_provider_retry(self, attempt: dict) -> None:
        """重试回调：记录到 last_retry（结构化 Error Event 的数据源）。"""
        self.last_retry = attempt


# 兼容别名：规范名是 AgentCore；Agent 仅为兼容旧用法保留。
Agent = AgentCore

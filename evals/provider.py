"""脚本化 Provider — 确定性模型步骤驱动。

Golden Task 的模型行为完全由 ``ProviderStep`` 序列决定：每一步要么返回
纯文本（content），要么返回一组工具调用。真实模型质量不在此评测——
评测的是引擎在给定模型行为下是否产生确定性的状态、工具、副作用与
Artifact（M0 §5.3）。

chunk 形状与 ``AgentCore.generate_messages`` 的属性访问契约一致
（``chunk.choices[0].delta.{content,reasoning_content,tool_calls}``，
tool_call delta 为 ``{index,id,type,function:{name,arguments}}``）。
"""

from __future__ import annotations

import json
from typing import Any

from .task import ProviderStep


class EvalDelta:
    """流式 delta（属性访问契约）。"""

    def __init__(
        self,
        *,
        content: str | None = None,
        reasoning_content: str | None = None,
        tool_calls: list["EvalToolCallDelta"] | None = None,
    ) -> None:
        self.content = content
        self.reasoning_content = reasoning_content
        self.tool_calls = tool_calls


class EvalToolCallFunctionDelta:
    def __init__(self, *, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class EvalToolCallDelta:
    def __init__(self, *, index: int, id: str, name: str, arguments: str) -> None:
        self.index = index
        self.id = id
        self.type = "function"
        self.function = EvalToolCallFunctionDelta(name=name, arguments=arguments)


class EvalChoice:
    def __init__(self, delta: EvalDelta) -> None:
        self.delta = delta


class EvalChunk:
    """OpenAI 兼容的流式 chunk。"""

    def __init__(
        self,
        *,
        content: str | None = None,
        reasoning: str | None = None,
        tool_calls: list[EvalToolCallDelta] | None = None,
        usage: dict | None = None,
    ) -> None:
        delta = EvalDelta(
            content=content,
            reasoning_content=reasoning,
            tool_calls=tool_calls,
        )
        self.choices: list[EvalChoice] = []
        if content is not None or reasoning is not None or tool_calls is not None:
            self.choices.append(EvalChoice(delta))
        self.usage = usage


class ScriptedProvider:
    """按步骤序列回复的确定性 Provider。

    ``complete(messages, tools)`` 返回一个 async 流。每一步消耗一个
    ProviderStep：text 步骤产出 content chunk；tools 步骤产出
    tool_calls chunk（调用 ID 自动生成，arguments 序列化为 JSON 字符串）。

    步骤耗尽后返回空回复（结束循环）。
    """

    def __init__(
        self,
        steps: list[ProviderStep] | tuple[ProviderStep, ...],
        *,
        model: str = "eval-model",
    ) -> None:
        self.steps: list[ProviderStep] = list(steps)
        self.model = model
        self.calls: list[dict[str, Any]] = []
        self._call_seq = 0

    async def complete(self, messages, tools=None, **run_kwargs) -> Any:
        self.calls.append({"messages": messages, "tools": tools, **run_kwargs})
        if not self.steps:
            return self._stream([])
        step = self.steps.pop(0)

        if step.type == "text":
            chunks = []
            if step.reasoning:
                chunks.append(EvalChunk(reasoning=step.reasoning))
            chunks.append(EvalChunk(content=step.content))
        elif step.type == "tools":
            tc: list[EvalToolCallDelta] = []
            for call in step.calls:
                self._call_seq += 1
                tc.append(
                    EvalToolCallDelta(
                        index=self._call_seq - 1,
                        id=f"call_{self._call_seq}",
                        name=call["name"],
                        arguments=_json_dumps(call.get("arguments", {})),
                    )
                )
            chunks = [EvalChunk(tool_calls=tc)]
        else:
            raise ValueError(f"未知 provider 步骤类型: {step.type!r}")

        return self._stream(chunks)

    @staticmethod
    def _stream(chunks: list[EvalChunk]) -> Any:
        async def stream():
            for chunk in chunks:
                yield chunk

        return stream()


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)

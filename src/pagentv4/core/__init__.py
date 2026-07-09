"""pagentv4.core —— agent core 抽象层。

只放「一次任务过程中必备的类型 + 抽象」：
- AgentCore 配置主体
- Message / Messages 状态
- Provider 契约
- @tool / FunctionTool
- Event / TurnResult

不涉及编排（Runner）、持久化、沙箱、协议适配等落地问题。
"""

from .agent import Agent, AgentCore
from .events import (
    Event,
    ReasoningDelta,
    RunBegin,
    RunEnd,
    StopReason,
    TextDelta,
    ToolCallBegin,
    ToolResult,
    TurnBegin,
    TurnEnd,
)
from .message import (
    AssistantChunk,
    AudioUrl,
    ImageUrl,
    Message,
    Messages,
    TextChunk,
    ThinkingChunk,
    ToolCall,
    UserChunk,
    reply_text,
)
from .provider import (
    DeepSeek,
    Kimi,
    LongCat,
    MiMo,
    Ollama,
    Provider,
    ProviderProtocol,
    Sglang,
    Vllm,
)
from .tool import FunctionTool, ToolOutput, to_openai_tools, tool
from .turn_result import TurnResult

__all__ = [
    "Agent",
    "AgentCore",
    "AssistantChunk",
    "AudioUrl",
    "DeepSeek",
    "Event",
    "FunctionTool",
    "ImageUrl",
    "Kimi",
    "LongCat",
    "Message",
    "Messages",
    "MiMo",
    "Ollama",
    "Provider",
    "ProviderProtocol",
    "ReasoningDelta",
    "RunBegin",
    "RunEnd",
    "Sglang",
    "StopReason",
    "TextChunk",
    "TextDelta",
    "ThinkingChunk",
    "ToolCall",
    "ToolCallBegin",
    "ToolOutput",
    "ToolResult",
    "TurnBegin",
    "TurnEnd",
    "TurnResult",
    "UserChunk",
    "Vllm",
    "reply_text",
    "to_openai_tools",
    "tool",
]

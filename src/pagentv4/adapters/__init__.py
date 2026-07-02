"""pagentv4.adapters —— 事件与外部协议的编解码。

目前只有 ACP（JSON-RPC 事件行）。后续新协议加同级模块即可，命名保持简短。
"""

from .acp import decode_event_line, encode_event_line

__all__ = [
    "decode_event_line",
    "encode_event_line",
]

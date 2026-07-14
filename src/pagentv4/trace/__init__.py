"""轨迹导出与可视化 —— 把 messages.jsonl 渲染成 HTML/文本或导出为 OpenAI 格式。

- io:            从 jsonl / thread id / stdin 加载 Messages
- view:          渲染成 HTML 或终端文本（pagent-trace CLI）
- openai_export: 转成 OpenAI Chat Completions messages JSON（pagent-openai CLI）
"""

from .io import load_messages, resolve_messages_path
from .openai_export import messages_to_openai_json
from .view import render_html, render_text, write_trace

__all__ = [
    "load_messages",
    "messages_to_openai_json",
    "render_html",
    "render_text",
    "resolve_messages_path",
    "write_trace",
]

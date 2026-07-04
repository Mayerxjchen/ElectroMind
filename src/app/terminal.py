"""prompt_toolkit 终端 I/O — 统一输入与输出（替代裸 print / input / stdout.write）。"""

from __future__ import annotations

import sys
from typing import TextIO

from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.formatted_text import ANSI, FormattedText

_session: PromptSession | None = None


def prompt_session() -> PromptSession:
    global _session
    if _session is None:
        _session = PromptSession()
    return _session


def _builtin_emit(
    text: str,
    *,
    end: str,
    file: TextIO | None,
    flush: bool,
) -> None:
    print(text, end=end, file=file, flush=flush)


def emit(
    text: str = "",
    *,
    end: str = "\n",
    file: TextIO | None = None,
    flush: bool = False,
) -> None:
    """打印一行或多行；字符串含 ANSI 转义时自动走 :class:`ANSI` 解析。"""
    stream = file or sys.stdout
    buffer = getattr(stream, "buffer", None)
    if buffer is not None and getattr(buffer, "closed", False):
        _builtin_emit(text, end=end, file=file, flush=flush)
        return

    payload: str | ANSI = ANSI(text) if "\033[" in text else text
    try:
        print_formatted_text(payload, end=end, file=file, flush=flush)
    except ValueError:
        _builtin_emit(text, end=end, file=file, flush=flush)


def emit_prompt(message: str | FormattedText | ANSI) -> str:
    return prompt_session().prompt(message)

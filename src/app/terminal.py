"""prompt_toolkit 终端 I/O — 统一输入与输出（替代裸 print / input / stdout.write）。"""

from __future__ import annotations

import asyncio
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, TextIO

from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.formatted_text import ANSI, FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.patch_stdout import patch_stdout

_session: PromptSession | None = None
_patched_stdout: ContextVar[bool] = ContextVar("patched_stdout", default=False)
# TUI 输出适配器（NoticeSink 等）：emit() 在 TUI 模式下把文本送进时间线。
layout_terminal: ContextVar[object | None] = ContextVar("layout_terminal", default=None)


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
    """打印一行或多行。

    并发 REPL（``stdout_patch``）内走标准 ``print``，由 patch_stdout 画在 prompt 上方；
    其余场景用 ``print_formatted_text`` + ``ANSI``。
    """
    layout = layout_terminal.get()
    if layout is not None and file is None:
        layout.write(text, end=end)
        return

    if _patched_stdout.get() and file is None:
        _builtin_emit(text, end=end, file=file, flush=flush)
        return

    stream = file or sys.stdout
    buffer = getattr(stream, "buffer", None)
    if buffer is not None and getattr(buffer, "closed", False):
        _builtin_emit(text, end=end, file=file, flush=flush)
        return

    # prompt_toolkit 的 print_formatted_text 会为终端兼容把换行写成 \r\n；
    # 非 TTY（管道、测试捕获、StringIO）下应使用平台原生换行 \n。
    if not stream.isatty():
        _builtin_emit(text, end=end, file=file, flush=flush)
        return

    payload: str | ANSI = ANSI(text) if "\033[" in text else text
    try:
        print_formatted_text(payload, end=end, file=file, flush=flush)
    except ValueError:
        _builtin_emit(text, end=end, file=file, flush=flush)


@contextmanager
def stdout_patch() -> Iterator[None]:
    """与 ``prompt_async`` 同用：输出固定在底栏 prompt 上方。"""
    token = _patched_stdout.set(True)
    try:
        with patch_stdout(raw=True):
            yield
    finally:
        _patched_stdout.reset(token)


def emit_prompt(message: str | FormattedText | ANSI) -> str:
    return prompt_session().prompt(message)


async def emit_prompt_async(
    message: str | FormattedText | ANSI,
    *,
    session: PromptSession | None = None,
) -> str:
    return await (session or prompt_session()).prompt_async(message)


async def start_prompt(
    message: str | FormattedText | ANSI,
    *,
    session: PromptSession,
) -> asyncio.Task[str]:
    task = asyncio.create_task(emit_prompt_async(message, session=session))
    await asyncio.sleep(0)
    return task


async def replace_prompt(
    prompt_task: asyncio.Task[str],
    *,
    message: str | FormattedText | ANSI,
    session: PromptSession,
) -> asyncio.Task[str]:
    if not prompt_task.done():
        prompt_task.cancel()
        try:
            await prompt_task
        except asyncio.CancelledError:
            pass
    task = asyncio.create_task(emit_prompt_async(message, session=session))
    await asyncio.sleep(0)
    return task


async def next_prompt(
    prompt_task: asyncio.Task[str],
    message: str | FormattedText | ANSI,
    *,
    session: PromptSession,
) -> asyncio.Task[str]:
    if prompt_task.done():
        return await start_prompt(message, session=session)
    return await replace_prompt(prompt_task, message=message, session=session)


def build_prompt_session(runner, run_state: dict) -> PromptSession:
    kb = KeyBindings()

    @kb.add("c-c")
    def cancel_or_exit(event) -> None:
        if run_state.get("active"):
            runner.cancel_run()
            event.app.invalidate()
        else:
            event.app.exit(exception=KeyboardInterrupt())

    @kb.add("escape")
    def cancel_run(event) -> None:
        if run_state.get("active"):
            runner.cancel_run()
            event.app.invalidate()

    return PromptSession(key_bindings=kb)

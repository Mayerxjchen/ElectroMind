"""Coverage + 行为：app/terminal.py 的 emit 分支与 stdout_patch。

覆盖 emit 的 layout 适配 / patched-stdout / 关闭 buffer / 非 TTY / ValueError
降级路径，以及 stdout_patch 上下文。补足 A+ v1.0 真实覆盖率。
"""

from __future__ import annotations

import io

import pytest


class _Sink:
    """layout_terminal 适配器（NoticeSink 语义）。"""

    def __init__(self):
        self.writes: list[str] = []

    def write(self, text: str = "", *, end: str = "\n") -> None:
        self.writes.append(text + end)

    def invalidate(self) -> None:
        pass


class TestEmit:
    def test_emit_to_layout(self):
        """layout_terminal 存在且 file=None → 走 layout。"""
        from app import terminal

        sink = _Sink()
        token = terminal.layout_terminal.set(sink)
        try:
            terminal.emit("hello")
        finally:
            terminal.layout_terminal.reset(token)
        assert sink.writes == ["hello\n"]

    def test_emit_to_layout_custom_end(self):
        from app import terminal

        sink = _Sink()
        token = terminal.layout_terminal.set(sink)
        try:
            terminal.emit("x", end="")
        finally:
            terminal.layout_terminal.reset(token)
        assert sink.writes == ["x"]

    def test_emit_ignores_layout_when_file_given(self, tmp_path):
        """file 显式给出 → 忽略 layout，写文件。"""
        from app import terminal

        sink = _Sink()
        token = terminal.layout_terminal.set(sink)
        try:
            out = io.StringIO()
            terminal.emit("to-file", file=out)
            assert out.getvalue() == "to-file\n"
            assert sink.writes == []  # 未走 layout
        finally:
            terminal.layout_terminal.reset(token)

    def test_emit_patched_stdout_uses_builtin(self):
        from app import terminal

        token = terminal._patched_stdout.set(True)
        try:
            out = io.StringIO()
            terminal.emit("patched", file=out)
            assert out.getvalue() == "patched\n"
        finally:
            terminal._patched_stdout.reset(token)

    def test_emit_non_tty_writes_native_newline(self):
        """非 TTY 流 → 平台原生换行（\n）。"""
        from app import terminal

        out = io.StringIO()
        terminal.emit("line1\nline2", file=out)
        assert out.getvalue() == "line1\nline2\n"

    def test_emit_closed_buffer_falls_back_to_builtin(self, monkeypatch):
        """buffer.closed=True → 降级 _builtin_emit（验证该分支被命中）。

        io.StringIO 没有 buffer 属性，且关闭后 emit 会在 isatty() 抛
        ValueError —— 用带 closed buffer 的假 TextIO 精确构造该分支。
        """
        from app import terminal

        class _ClosedBuffer:
            closed = True

        class _FakeStream:
            """TextIO-like：isatty False、有已关闭的 buffer。"""

            buffer = _ClosedBuffer()

            def isatty(self) -> bool:
                return False

        calls: list[tuple] = []

        def _fake_builtin_emit(text, *, end, file, flush):
            calls.append((text, end, file, flush))

        monkeypatch.setattr(terminal, "_builtin_emit", _fake_builtin_emit)
        terminal.emit("x", file=_FakeStream())
        assert calls  # 走到 buffer.closed → _builtin_emit 分支
        assert calls[0][0] == "x"


class TestStdoutPatch:
    def test_stdout_patch_context(self):
        from app import terminal

        assert terminal._patched_stdout.get() is False
        with terminal.stdout_patch():
            assert terminal._patched_stdout.get() is True
        assert terminal._patched_stdout.get() is False

    def test_stdout_patch_restores_on_error(self):
        from app import terminal

        with pytest.raises(RuntimeError):
            with terminal.stdout_patch():
                raise RuntimeError("boom")
        assert terminal._patched_stdout.get() is False

"""prompt_toolkit 组件：Transcript / StatusLine / Composer / ApprovalCard / Popup。

唯一 TUI 所有者是 prompt_toolkit；所有内容都来自 CliViewModel/ItemStore，
组件内部不产生业务状态。
"""

from __future__ import annotations

from prompt_toolkit.buffer import Buffer
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.layout.containers import (
    Window,
)
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.scrollable_pane import ScrollablePane

from .store import ItemStore
from .theme import CYAN, DIM, RED, YELLOW, c
from .view_model import StatusLineState


class OutputScrollPane(ScrollablePane):
    """Transcript 滚动：约束在视口内；未 pinned 时跟随底部。"""

    stick_to_bottom: bool = True

    def write_to_screen(
        self,
        screen,
        mouse_handlers,
        write_position,
        parent_style,
        erase_bg,
        z_index,
    ) -> None:
        virtual_width = write_position.width - (1 if self.show_scrollbar() else 0)
        virtual_height = self.content.preferred_height(
            virtual_width, self.max_available_height
        ).preferred
        virtual_height = max(virtual_height, write_position.height)
        virtual_height = min(virtual_height, self.max_available_height)
        max_scroll = max(0, virtual_height - write_position.height)

        if self.stick_to_bottom:
            self.vertical_scroll = max_scroll
        else:
            self.vertical_scroll = min(self.vertical_scroll, max_scroll)

        super().write_to_screen(
            screen,
            mouse_handlers,
            write_position,
            parent_style,
            erase_bg,
            z_index,
        )


def transcript_pane(store: ItemStore, *, pinned: bool = False) -> Window:
    pane = OutputScrollPane(
        Window(
            FormattedTextControl(lambda: _store_text(store)),
            wrap_lines=True,
            dont_extend_height=False,
        ),
        width=Dimension(weight=1),
        height=Dimension(weight=1),
        keep_cursor_visible=False,
        keep_focused_window_visible=False,
    )
    pane.stick_to_bottom = not pinned
    return pane


def _store_text(store: ItemStore):
    """当前终端宽度下的时间线文本（验收 G-7：get_cwidth 需传字符串，改用终端尺寸）。"""
    import shutil

    width = shutil.get_terminal_size((100, 24)).columns
    lines = store.render_lines(width)
    if "\033[" in "".join(lines):
        return ANSI("\n".join(lines))
    return "\n".join(lines)


def status_line_text(status: StatusLineState, *, color: bool) -> str:
    """状态行：RUN · sandbox · prompt · model · project · ctx 31%。"""
    run_code = {
        "approval": YELLOW,
        "cancelling": RED,
        "generating": CYAN,
        "running_tool": CYAN,
    }.get(status.run_status, DIM)
    segments: list[str] = []
    for idx, text in enumerate(status.segments()):
        if idx == 0:
            segments.append(c(text, run_code, on=color))
        else:
            segments.append(c(text, DIM, on=color))
    return " · ".join(segments)


def status_line(store: ItemStore, status: StatusLineState) -> Window:
    return Window(
        FormattedTextControl(lambda: status_line_text(status, color=store.color)),
        height=Dimension.exact(1),
    )


def composer_window(
    buffer: Buffer,
    *,
    get_prefix,
    completer=None,
) -> Window:
    if completer is not None:
        # completer 挂在 Buffer 上（BufferControl 不接受 completer 参数）
        buffer.completer = completer
        buffer.complete_while_typing = False
    return Window(
        BufferControl(
            buffer=buffer,
            focusable=True,
        ),
        height=Dimension.exact(1),
        get_line_prefix=lambda _ln, _wc: [("", get_prefix())],
    )


def approval_card(
    title: str,
    body: list[str],
    *,
    color: bool,
) -> Window:
    """Approval 卡片：半高浮层，含命令 / Target / Workdir / Risk。

    验收 G-7：按显示宽度（CJK=2）对齐，缩放与中英文不错位。
    """
    from ..render import display_width

    width = 60  # 内容显示宽度（不含左右边框）

    def row(text: str, *, code: str = "") -> str:
        pad = width - 2 - display_width(text)
        return f"│ {text}{' ' * max(0, pad)} │"

    def border(char: str = "─") -> str:
        return f"┌{char * width}┐" if char == "─" else f"└{char * width}┘"

    lines: list[str] = [c(border("─"), YELLOW, on=color)]
    lines.append(c(row(" Approval required "), YELLOW, on=color))
    for line in body[:8]:
        lines.append(row(line))
    lines.append(row("[Enter] Approve  [Esc] Cancel run"))
    lines.append(
        c(row("（输入框清空时按 y/n/d；有输入时按键为普通文本）"), DIM, on=color)
    )
    lines.append(c(border("─"), YELLOW, on=color))
    text = "\n".join(lines)
    return Window(
        FormattedTextControl(ANSI(text) if "\033[" in text else text),
        width=width + 2,
        height=len(lines),
        style="class:approval-card",
    )

"""全屏布局终端 — 输出区在上、输入行钉在视口最底。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import has_focus
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.scrollable_pane import ScrollablePane


class OutputScrollPane(ScrollablePane):
    """输出区滚动：约束在视口内，新内容时跟随到底。"""

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


@dataclass
class LayoutTerminal:
    color: bool
    input_queue: asyncio.Queue[str | None] = field(default_factory=asyncio.Queue)
    body: str = ""
    prompt_prefix: str = "you> "
    app: Application | None = None
    input_buffer: Buffer = field(default_factory=Buffer)
    output_pane: OutputScrollPane | None = None

    def set_prefix(self, prefix: str) -> None:
        self.prompt_prefix = prefix
        if self.app is not None:
            self.app.invalidate()

    def write(self, text: str = "", *, end: str = "\n") -> None:
        self.body += text + end
        if self.output_pane is not None:
            self.output_pane.stick_to_bottom = True
        if self.app is not None:
            self.app.invalidate()

    def output_fragments(self):
        if "\033[" in self.body:
            return ANSI(self.body)
        return self.body

    def build_application(
        self,
        *,
        run_state: dict,
        runner,
    ) -> Application:
        kb = KeyBindings()

        @kb.add("enter", filter=has_focus(self.input_buffer))
        def submit(event) -> None:
            line = self.input_buffer.text
            self.input_buffer.reset()
            self.input_queue.put_nowait(line)

        @kb.add("c-c")
        def cancel_or_exit(event) -> None:
            if run_state.get("active"):
                runner.cancel_run()
                event.app.invalidate()
            else:
                self.input_queue.put_nowait(None)
                event.app.exit()

        @kb.add("escape")
        def cancel_run(event) -> None:
            if run_state.get("active"):
                runner.cancel_run()
                event.app.invalidate()

        output = Window(
            FormattedTextControl(self.output_fragments),
            wrap_lines=True,
            dont_extend_height=False,
        )
        self.output_pane = OutputScrollPane(
            output,
            width=Dimension(weight=1),
            height=Dimension(weight=1),
            keep_cursor_visible=False,
            keep_focused_window_visible=False,
        )
        input_row = Window(
            BufferControl(buffer=self.input_buffer, focusable=True),
            height=Dimension.exact(1),
            get_line_prefix=lambda _ln, _wc: [("", self.prompt_prefix)],
        )

        @kb.add(Keys.PageUp)
        def scroll_output_up(event) -> None:
            pane = self.output_pane
            if pane is None:
                return
            pane.stick_to_bottom = False
            step = max(1, event.app.output.get_size().rows - 2)
            pane.vertical_scroll = max(0, pane.vertical_scroll - step)
            event.app.invalidate()

        @kb.add(Keys.PageDown)
        def scroll_output_down(event) -> None:
            pane = self.output_pane
            if pane is None:
                return
            step = max(1, event.app.output.get_size().rows - 2)
            pane.vertical_scroll += step
            event.app.invalidate()

        layout = Layout(
            HSplit(
                [
                    self.output_pane,
                    input_row,
                ]
            )
        )
        self.app = Application(
            layout=layout,
            key_bindings=kb,
            full_screen=True,
        )
        return self.app

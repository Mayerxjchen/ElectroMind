from __future__ import annotations

import json
import re
import shutil
import sys
import unicodedata
from dataclasses import dataclass, field

from pagentv4 import (
    ReasoningDelta,
    Runner,
    TextDelta,
    ToolCallBegin,
    ToolResult,
    TurnEnd,
)

from .terminal import emit
from .tool_permit import (
    needs_tool_permit,
    prompt_permit_blocking,
    runner_supports_permit,
    wait_for_layout_permit,
)

CYAN = "\033[36m"
DIM = "\033[90m"
GREEN = "\033[32m"
RED = "\033[31m"
BLUE = "\033[34m"
YELLOW = "\033[33m"
RESET = "\033[0m"

INNER = 54  # display columns between │ borders
LABEL_WIDTH = 8
VALUE_WIDTH = INNER - 1 - LABEL_WIDTH  # leading space after │
TOOL_LINE = 100
TOOL_VALUE = 48
TOOL_RESULT = 120
TOOL_RESULT_LINES = 3
ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def char_display_width(ch: str) -> int:
    if unicodedata.combining(ch):
        return 0
    codepoint = ord(ch)
    if codepoint <= 0x7F or 0x2500 <= codepoint <= 0x259F:
        return 1
    if unicodedata.east_asian_width(ch) in ("F", "W"):
        return 2
    return 1


def display_width(text: str) -> int:
    return sum(char_display_width(ch) for ch in strip_ansi(text))


def shorten_display(text: str, width: int) -> str:
    if display_width(text) <= width:
        return text
    if width <= 1:
        return "…"[:width]
    head_budget = max(1, (width - 1) // 2)
    tail_budget = max(1, width - 1 - head_budget)

    head: list[str] = []
    used = 0
    for ch in text:
        cw = char_display_width(ch)
        if used + cw > head_budget:
            break
        head.append(ch)
        used += cw

    tail: list[str] = []
    used = 0
    for ch in reversed(text):
        cw = char_display_width(ch)
        if used + cw > tail_budget:
            break
        tail.append(ch)
        used += cw

    return f"{''.join(head)}…{''.join(reversed(tail))}"


def shorten(text: str, width: int) -> str:
    return shorten_display(text, width)


def pad_display(text: str, width: int) -> str:
    padding = width - display_width(text)
    if padding <= 0:
        return text
    return f"{text}{' ' * padding}"


def box_line_width() -> int:
    return INNER + 2


def box_top(*, color: bool) -> str:
    prefix = "╭─ pagent "
    bar = "─" * (box_line_width() - display_width(prefix) - 1)
    return c(f"{prefix}{bar}╮", CYAN, on=color)


def box_bottom(*, color: bool) -> str:
    return c(f"╰{'─' * (box_line_width() - 1)}╯", DIM, on=color)


def c(text: str, code: str, *, on: bool) -> str:
    return f"{code}{text}{RESET}" if on else text


def emit_user_line(text: str, *, color: bool, user_label: str = "you") -> None:
    emit(c(f"{user_label}> {text}", BLUE, on=color))


def format_assistant_line(
    body: str, *, color: bool, assistant_label: str = "pagent"
) -> str:
    line = f"{assistant_label}> {body}"
    return c(line, GREEN, on=color) if color else line


def inline(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def terminal_width(*, fallback: int = 100) -> int:
    return shutil.get_terminal_size((fallback, 24)).columns


def wrap_visual_lines(text: str, *, width: int) -> list[str]:
    if width <= 1:
        return [text[:1]] if text else [""]

    pieces: list[str] = []
    for raw_line in text.splitlines() or [""]:
        line = raw_line.rstrip()
        if not line:
            pieces.append("")
            continue
        start = 0
        while start < len(line):
            pieces.append(line[start : start + width])
            start += width
    return pieces or [""]


def summarize_visual_text(text: str, *, width: int, max_lines: int) -> str:
    lines = wrap_visual_lines(text, width=width)
    visible = lines[:max_lines]
    summary = " ".join(part for part in visible if part)
    if not summary and visible:
        summary = visible[0]
    omitted = len(lines) - len(visible)
    if omitted > 0:
        suffix = f" …(+{omitted} lines)"
        available = max(1, width - len(suffix))
        summary = shorten(summary, available) + suffix
    return summary


def format_tool_value(value: object, *, width: int = TOOL_VALUE) -> str:
    if isinstance(value, str):
        return shorten(repr(inline(value)), width)
    if isinstance(value, bool | int | float) or value is None:
        return shorten(repr(value), width)
    try:
        compact = json.dumps(value, ensure_ascii=False, separators=(", ", ": "))
    except TypeError:
        compact = repr(value)
    return shorten(inline(compact), width)


def summarize_tool_arguments(arguments: str, *, width: int = TOOL_LINE) -> str:
    text = inline(arguments)
    if not text:
        return ""
    try:
        payload = json.loads(arguments)
    except json.JSONDecodeError:
        return shorten(text, width)

    if isinstance(payload, dict):
        parts: list[str] = []
        for key, value in payload.items():
            parts.append(f"{key}={format_tool_value(value)}")
        return shorten(", ".join(parts), width)

    return shorten(format_tool_value(payload, width=width), width)


def format_tool_call(name: str, arguments: str) -> str:
    summary = summarize_tool_arguments(arguments)
    if not summary:
        return f"tool → {name}()"
    return f"tool → {name}({summary})"


def format_tool_result(content: str, *, ok: bool) -> str:
    width = min(TOOL_RESULT, max(24, terminal_width() - 8))
    body = summarize_visual_text(content, width=width, max_lines=TOOL_RESULT_LINES)
    mark = "ok" if ok else "fail"
    return f"{mark}: {body}"


def row(key: str, value: str, *, color: bool, value_code: str = "") -> str:
    label = f"{key:<{LABEL_WIDTH}}"
    value_plain = shorten_display(value, VALUE_WIDTH)
    pad = VALUE_WIDTH - display_width(value_plain)
    if color:
        label_rendered = c(label, DIM, on=True)
        value_rendered = (
            c(value_plain, value_code, on=True)
            if value_code
            else c(value_plain, DIM, on=True)
        )
    else:
        label_rendered = label
        value_rendered = value_plain
    body = f" {label_rendered}{value_rendered}{' ' * pad}"
    return f"│{body}│"


def format_sandbox_line(runner: Runner) -> str:
    thread = runner.thread
    backend = thread.spec.backend
    if backend == "ssh":
        alias = thread.spec.ssh_host or "?"
        conn = (runner.sandbox.spec.connection or {}) if runner.sandbox.spec else {}
        user = conn.get("user", "")
        host = conn.get("host", "")
        target = f"{user}@{host}" if user and host else alias
        return f"ssh · {alias} · {target}"
    if backend in ("docker", "podman"):
        image = thread.spec.image or "?"
        return f"{backend} · {image} · {runner.sandbox.home}"
    return f"local · {runner.sandbox.home}"


def format_banner(runner: Runner, *, color: bool) -> str:
    thread = runner.thread
    status = "新建" if thread.created else "续聊"
    status_color = YELLOW if thread.created else GREEN

    model = thread.spec.model or "deepseek-v4-flash"
    sandbox = format_sandbox_line(runner)
    workdir = runner.sandbox.workdir
    turns = sum(1 for m in runner.messages.data if m.role == "user")
    skills = ", ".join(runner.skills.names()) or "—"

    top = box_top(color=color)
    bottom = box_bottom(color=color)

    lines = [
        top,
        row("thread", f"{thread.id} · {status}", color=color, value_code=status_color),
        row("model", model, color=color),
        row("sandbox", sandbox, color=color),
        row("workdir", workdir, color=color),
        row("turns", f"{turns} prior · max {runner.agent.max_turns}", color=color),
        row("skills", skills, color=color),
        bottom,
    ]

    if thread.spec.backend == "ssh":
        lines.insert(
            5,
            row("messages", str(thread.messages_storage_path), color=color),
        )

    if thread.ignored_overrides:
        ignored = ", ".join(thread.ignored_overrides)
        note = shorten(f"spec 已冻结，忽略：{ignored}", INNER)
        lines.append(c(f"  {note}", DIM, on=color))

    lines.append(c("  /exit  /pwd  /ls  /skills  /history", BLUE, on=color))
    lines.append(c("  !!cmd sandbox  ·  !cmd host", BLUE, on=color))
    lines.append("")
    return "\n".join(lines)


def print_command_header(target: str, command: str, *, color: bool) -> None:
    palette = CYAN if target == "sandbox" else YELLOW
    label = "sandbox" if target == "sandbox" else "host"
    line = f"{label}$ {command}"
    emit(c(line, palette, on=color))


def print_command_result(
    stdout: str, stderr: str, exit_code: int, *, color: bool
) -> None:
    has_stdout = bool(stdout)
    has_stderr = bool(stderr)

    if has_stdout:
        end = "" if stdout.endswith("\n") else "\n"
        emit(stdout, end=end)
    if has_stderr:
        text = c(stderr, RED, on=color) if color else stderr
        end = "" if stderr.endswith("\n") else "\n"
        emit(text, end=end, file=sys.stderr)
    if exit_code != 0 or (not has_stdout and not has_stderr):
        emit(c(f"[exit {exit_code}]", DIM, on=color))


@dataclass
class ToolBlock:
    tool_call_id: str
    name: str
    arguments: str
    call_preview: str
    result_preview: str = ""
    ok: bool | None = None


@dataclass
class RenderState:
    color: bool
    user_label: str = "you"
    assistant_label: str = "pagent"
    reasoning_parts: list[str] = field(default_factory=list)
    text_parts: list[str] = field(default_factory=list)
    previous_kind: str = ""
    tool_blocks: list[ToolBlock] = field(default_factory=list)

    def flush_reasoning(self) -> None:
        if not self.reasoning_parts:
            return
        prefix = "reasoning: "
        body = "".join(self.reasoning_parts)
        if self.color:
            emit(f"{DIM}{prefix}{body}{RESET}")
        else:
            emit(f"{prefix}{body}")
        self.reasoning_parts.clear()

    def flush_text(self) -> None:
        if not self.text_parts:
            return
        emit(
            format_assistant_line(
                "".join(self.text_parts),
                color=self.color,
                assistant_label=self.assistant_label,
            )
        )
        self.text_parts.clear()

    def flush_buffers(self) -> None:
        self.flush_reasoning()
        self.flush_text()

    def append_reasoning(self, text: str) -> None:
        if self.text_parts:
            self.flush_text()
        self.reasoning_parts.append(text)
        self.previous_kind = "reasoning"

    def append_text(self, text: str) -> None:
        if self.reasoning_parts:
            self.flush_reasoning()
        if self.previous_kind == "tool_result" and not self.text_parts:
            emit()
        self.text_parts.append(text)
        self.previous_kind = "text"

    def find_tool_block(self, tool_call_id: str) -> ToolBlock | None:
        for block in reversed(self.tool_blocks):
            if block.tool_call_id == tool_call_id:
                return block
        return None

    def print_tool_call(self, tool_call_id: str, name: str, arguments: str) -> None:
        self.flush_buffers()
        line = format_tool_call(name, arguments)
        self.tool_blocks.append(
            ToolBlock(
                tool_call_id=tool_call_id,
                name=name,
                arguments=arguments,
                call_preview=line,
            )
        )
        emit(f"{CYAN}{line}{RESET}" if self.color else line)
        self.previous_kind = "tool_call"

    def print_tool_result(self, tool_call_id: str, content: str, *, ok: bool) -> None:
        self.flush_buffers()
        line = format_tool_result(content, ok=ok)
        block = self.find_tool_block(tool_call_id)
        if block is None:
            block = ToolBlock(
                tool_call_id=tool_call_id,
                name="unknown",
                arguments="",
                call_preview="",
            )
            self.tool_blocks.append(block)
        block.result_preview = line
        block.ok = ok
        if self.color:
            palette = GREEN if ok else RED
            head, _, tail = line.partition(": ")
            line = f"{palette}{head}{RESET}"
            if tail:
                line += f": {tail}"
        emit(f"  {line}")
        self.previous_kind = "tool_result"

    def finish(self) -> None:
        if self.reasoning_parts:
            self.flush_reasoning()
            return
        if self.text_parts:
            self.flush_text()
            return
        emit()


def render_event(event, state: RenderState) -> None:
    if isinstance(event, ReasoningDelta):
        state.append_reasoning(event.text)
    elif isinstance(event, ToolCallBegin):
        state.print_tool_call(event.tool_call_id, event.name, event.arguments)
    elif isinstance(event, ToolResult):
        state.print_tool_result(event.tool_call_id, event.content, ok=event.ok)
    elif isinstance(event, TextDelta):
        state.append_text(event.text)
    elif isinstance(event, TurnEnd) and event.stop_reason == "cancelled":
        emit(c("[cancelled]", YELLOW, on=state.color))


async def consume_run(
    runner: Runner,
    user_input: str,
    state: RenderState,
    *,
    run_state: dict | None = None,
    permit_auto: bool = False,
) -> None:
    async for event in runner.run(user_input):
        render_event(event, state)
        if (
            not permit_auto
            and isinstance(event, ToolCallBegin)
            and needs_tool_permit(event.name)
            and runner_supports_permit(runner)
        ):
            if run_state is not None:
                await wait_for_layout_permit(
                    runner, event, run_state, color=state.color
                )
            else:
                await prompt_permit_blocking(runner, event, color=state.color)
    state.finish()


async def render_turn(
    runner: Runner,
    user_input: str,
    *,
    color: bool,
    state: RenderState | None = None,
    user_label: str = "you",
    assistant_label: str = "pagent",
    permit_auto: bool = False,
) -> RenderState:
    if state is None:
        state = RenderState(
            color=color,
            user_label=user_label,
            assistant_label=assistant_label,
        )
    await consume_run(runner, user_input, state, permit_auto=permit_auto)
    return state

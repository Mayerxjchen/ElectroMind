"""Visualize pagent trajectories as HTML or terminal text."""

from __future__ import annotations

import argparse
import html
import json
import sys
import webbrowser
from pathlib import Path

from ..core.message import (
    AudioUrl,
    ImageUrl,
    Message,
    Messages,
    TextChunk,
    ThinkingChunk,
    ToolCall,
    ToolResult,
)
from .io import load_messages, resolve_messages_path

ROLE_LABELS = {
    "system": "system",
    "user": "user",
    "assistant": "assistant",
    "tool": "tool",
}


def pretty_json(text: str) -> str:
    try:
        return json.dumps(json.loads(text), ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        return text


def esc(text: str) -> str:
    return html.escape(text)


def message_kind(message: Message) -> str:
    content = message.content
    if isinstance(content, TextChunk):
        return "text"
    if isinstance(content, ThinkingChunk):
        return "thinking"
    if isinstance(content, ToolCall):
        return "tool_call"
    if isinstance(content, ToolResult):
        return "tool_result"
    if isinstance(content, ImageUrl):
        return "image"
    if isinstance(content, AudioUrl):
        return "audio"
    return message.role


def render_message_body(message: Message) -> str:
    content = message.content
    if isinstance(content, TextChunk):
        return content.text
    if isinstance(content, ThinkingChunk):
        return content.text
    if isinstance(content, ToolCall):
        return (
            f"id: {content.id}\n"
            f"name: {content.name}\n"
            f"arguments:\n{pretty_json(content.arguments)}"
        )
    if isinstance(content, ToolResult):
        return f"tool_call_id: {content.tool_call_id}\n\n{content.text}"
    if isinstance(content, ImageUrl):
        return content.url
    if isinstance(content, AudioUrl):
        return f"{content.url}\n\n{content.text}"
    return str(content)


def group_by_turn(messages: Messages) -> list[tuple[int | None, list[Message]]]:
    if not messages.data:
        return []
    groups: list[tuple[int | None, list[Message]]] = []
    current_turn: int | None = None
    bucket: list[Message] = []
    for message in messages.data:
        turn = message.turn_id
        if turn != current_turn:
            if bucket:
                groups.append((current_turn, bucket))
            current_turn = turn
            bucket = [message]
        else:
            bucket.append(message)
    if bucket:
        groups.append((current_turn, bucket))
    return groups


def render_text(messages: Messages, *, title: str) -> str:
    lines = [title, ""]
    for turn_id, turn_messages in group_by_turn(messages):
        label = "system" if turn_id == 0 else f"turn {turn_id}"
        lines.append(f"=== {label} ===")
        for message in turn_messages:
            kind = message_kind(message)
            role = ROLE_LABELS[message.role]
            header = f"[{role}/{kind}]"
            if message.message_id:
                header += f" id={message.message_id[:8]}"
            lines.append(header)
            body = render_message_body(message)
            if body:
                lines.extend(body.splitlines())
            lines.append("")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_system_banner(message: Message, *, msg_index: int) -> str:
    text = esc(render_message_body(message))
    return f"""<section class="system-banner" id="msg-{msg_index}">
  <details>
    <summary><span class="fold-label">System prompt</span></summary>
    <pre>{text}</pre>
  </details>
</section>"""


def render_user_bubble(message: Message, *, msg_index: int) -> str:
    text = esc(render_message_body(message))
    return f"""<div class="chat-row user" id="msg-{msg_index}">
  <div class="avatar">U</div>
  <div class="bubble user"><div class="bubble-body">{text}</div></div>
</div>"""


def render_assistant_bubble(
    message: Message, *, msg_index: int, show_avatar: bool = True
) -> str:
    text = esc(render_message_body(message))
    row_class = "chat-row assistant"
    if not show_avatar:
        row_class += " assistant-row-no-avatar"
    avatar = '  <div class="avatar">A</div>\n' if show_avatar else ""
    return f"""<div class="{row_class}" id="msg-{msg_index}">
{avatar}  <div class="bubble assistant"><div class="bubble-body">{text}</div></div>
</div>"""


def render_thinking_panel(
    message: Message, *, msg_index: int, show_avatar: bool = False
) -> str:
    text = esc(render_message_body(message))
    row_class = "chat-row assistant thinking-row"
    if not show_avatar:
        row_class += " thinking-row-no-avatar"
    avatar = '  <div class="avatar">A</div>\n' if show_avatar else ""
    return f"""<div class="{row_class}" id="msg-{msg_index}">
{avatar}  <details class="thinking-panel">
    <summary><span class="fold-label">思考</span></summary>
    <div class="thinking-body">{text}</div>
  </details>
</div>"""


def render_tool_call_card(message: Message, *, msg_index: int) -> str:
    assert isinstance(message.content, ToolCall)
    call = message.content
    args = esc(pretty_json(call.arguments))
    return f"""<div class="chat-row assistant tool-row" id="msg-{msg_index}">
  <details class="tool-card call">
    <summary class="tool-head">
      <span class="tool-badge">函数调用</span>
      <code class="tool-name">{esc(call.name)}</code>
      <span class="tool-id">{esc(call.id)}</span>
    </summary>
    <div class="tool-label">arguments</div>
    <pre class="tool-code">{args}</pre>
  </details>
</div>"""


def render_tool_result_card(message: Message, *, msg_index: int) -> str:
    assert isinstance(message.content, ToolResult)
    result = message.content
    payload = result.text
    status_class = "ok"
    headline = "工具返回"
    body_html = f'<pre class="tool-code">{esc(payload)}</pre>'

    try:
        data = json.loads(payload)
        if isinstance(data, dict):
            ok = data.get("ok", True)
            status_class = "ok" if ok else "fail"
            headline = "工具返回 · 成功" if ok else "工具返回 · 失败"
            exit_code = data.get("exit_code")
            stdout = data.get("stdout", "")
            stderr = data.get("stderr", "")
            meta_bits = []
            if exit_code is not None:
                meta_bits.append(f"exit {exit_code}")
            if data.get("timed_out"):
                meta_bits.append("timed out")
            meta = (
                f'<div class="tool-meta">{esc(" · ".join(meta_bits))}</div>'
                if meta_bits
                else ""
            )
            chunks = []
            if stdout:
                chunks.append(
                    f'<div class="tool-label">stdout</div><pre class="tool-code stdout">{esc(stdout)}</pre>'
                )
            if stderr:
                chunks.append(
                    f'<div class="tool-label">stderr</div><pre class="tool-code stderr">{esc(stderr)}</pre>'
                )
            if chunks:
                body_html = meta + "".join(chunks)
            else:
                body_html = (
                    meta + f'<pre class="tool-code">{esc(pretty_json(payload))}</pre>'
                )
    except json.JSONDecodeError:
        pass

    return f"""<div class="chat-row tool tool-row" id="msg-{msg_index}">
  <details class="tool-card result {status_class}">
    <summary class="tool-head">
      <span class="tool-badge">{esc(headline)}</span>
      <span class="tool-id">{esc(result.tool_call_id)}</span>
    </summary>
    {body_html}
  </details>
</div>"""


def render_media_message(message: Message, *, msg_index: int) -> str:
    body = esc(render_message_body(message))
    role = message.role
    return f"""<div class="chat-row {role}" id="msg-{msg_index}">
  <div class="avatar">{esc(role)}</div>
  <div class="bubble {role} media"><div class="bubble-body">{body}</div></div>
</div>"""


def is_assistant_streak_message(message: Message) -> bool:
    if message.role != "assistant":
        return False
    return isinstance(message.content, (TextChunk, ThinkingChunk, ToolCall))


def breaks_assistant_streak(message: Message) -> bool:
    return message.role in ("user", "system", "tool")


def render_message_html(
    message: Message,
    *,
    msg_index: int,
    show_avatar: bool | None = None,
) -> str:
    content = message.content
    if message.role == "system":
        return render_system_banner(message, msg_index=msg_index)
    if isinstance(content, TextChunk) and message.role == "user":
        return render_user_bubble(message, msg_index=msg_index)
    if isinstance(content, TextChunk) and message.role == "assistant":
        return render_assistant_bubble(
            message,
            msg_index=msg_index,
            show_avatar=True if show_avatar is None else show_avatar,
        )
    if isinstance(content, ThinkingChunk):
        return render_thinking_panel(
            message,
            msg_index=msg_index,
            show_avatar=False if show_avatar is None else show_avatar,
        )
    if isinstance(content, ToolCall):
        return render_tool_call_card(message, msg_index=msg_index)
    if isinstance(content, ToolResult):
        return render_tool_result_card(message, msg_index=msg_index)
    return render_media_message(message, msg_index=msg_index)


def render_messages_html(
    messages: list[Message],
    msg_index_start: int,
    *,
    assistant_avatar_shown: bool = False,
) -> tuple[str, bool]:
    parts: list[str] = []
    for offset, message in enumerate(messages):
        msg_index = msg_index_start + offset
        if breaks_assistant_streak(message):
            assistant_avatar_shown = False
            parts.append(render_message_html(message, msg_index=msg_index))
        elif is_assistant_streak_message(message):
            show_avatar = not assistant_avatar_shown
            parts.append(
                render_message_html(
                    message, msg_index=msg_index, show_avatar=show_avatar
                )
            )
            if show_avatar:
                assistant_avatar_shown = True
        else:
            parts.append(render_message_html(message, msg_index=msg_index))
    return "\n".join(parts), assistant_avatar_shown


def scrubber_segment_class(message: Message) -> str:
    if message.role == "user":
        return "user"
    if message.role == "system":
        return "system"
    if message.role == "tool" or isinstance(message.content, (ToolCall, ToolResult)):
        return "tool"
    return "assistant"


def render_scrubber(messages: list[Message]) -> str:
    if not messages:
        return ""
    segments = []
    for index, message in enumerate(messages):
        role_class = scrubber_segment_class(message)
        label = ROLE_LABELS.get(message.role, message.role)
        segments.append(
            f'<button type="button" class="scrub-seg {role_class}" '
            f'data-target="msg-{index}" title="{esc(label)}" '
            f'aria-label="{esc(label)}"></button>'
        )
    return (
        f'<nav class="scrubber" aria-label="Jump to message">{"".join(segments)}</nav>'
    )


def render_turn_html(
    turn_id: int | None,
    turn_messages: list[Message],
    msg_index_start: int,
    *,
    assistant_avatar_shown: bool = False,
) -> tuple[str, bool]:
    items, assistant_avatar_shown = render_messages_html(
        turn_messages,
        msg_index_start,
        assistant_avatar_shown=assistant_avatar_shown,
    )
    if turn_id == 0:
        return items, assistant_avatar_shown

    label = f"Turn {turn_id}"
    block = f"""<section class="turn" id="turn-{turn_id}">
  <div class="turn-marker"><span>{esc(label)}</span></div>
  <div class="turn-chat">{items}</div>
</section>"""
    return block, assistant_avatar_shown


TRACE_STYLES = """
:root {
  color-scheme: light;
  --bg: #f0f2f5;
  --panel: #ffffff;
  --text: #1f2937;
  --muted: #94a3b8;
  --line: #e8edf2;
  --user-bg: #2f6fed;
  --user-text: #ffffff;
  --user-border: #2f6fed;
  --assistant-bg: #1f9d6a;
  --assistant-text: #ffffff;
  --assistant-border: #1f9d6a;
  --thinking-bg: #f8fafc;
  --thinking-border: #dbe3ec;
  --thinking-text: #64748b;
  --tool-call-bg: #ffffff;
  --tool-call-border: #dbe3ec;
  --tool-ok-bg: #ffffff;
  --tool-ok-border: #cfe8d8;
  --tool-fail-bg: #ffffff;
  --tool-fail-border: #f0cfcf;
  --shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  --assistant-content-width: 100%;
  --assistant-header-min-height: 40px;
  --assistant-header-pad: 10px 14px;
  --assistant-header-line: 1.4;
  --user-content-max: 420px;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font: 14px/1.65 ui-sans-serif, system-ui, -apple-system, sans-serif;
  background: var(--bg);
  color: var(--text);
}
main {
  max-width: 860px;
  margin: 0 auto;
  padding: 32px 20px 64px;
}
.page-title {
  margin: 0 0 28px;
  font-size: 18px;
  font-weight: 600;
  color: #475569;
  letter-spacing: -0.01em;
}
.system-banner {
  margin-bottom: 28px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 12px;
  box-shadow: var(--shadow);
  overflow: hidden;
}
.system-banner summary,
.thinking-panel > summary,
.tool-card > summary {
  cursor: pointer;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  min-height: var(--assistant-header-min-height);
  padding: var(--assistant-header-pad);
  line-height: var(--assistant-header-line);
  font-weight: 500;
  font-size: 13px;
  color: #64748b;
  list-style: none;
  -webkit-user-select: none;
  user-select: none;
}
.system-banner summary::-webkit-details-marker,
.thinking-panel > summary::-webkit-details-marker,
.tool-card > summary::-webkit-details-marker { display: none; }
.system-banner summary > *,
.thinking-panel > summary > *,
.tool-card > summary > * {
  -webkit-user-select: none;
  user-select: none;
}
.system-banner pre,
.thinking-body,
.tool-code,
.tool-label,
.tool-meta {
  -webkit-user-select: text;
  user-select: text;
}
.system-banner pre,
.thinking-body,
.tool-code {
  margin: 0;
  padding: 14px 16px;
  white-space: pre-wrap;
  word-break: break-word;
  font: 12px/1.7 ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #475569;
}
.turn { margin-bottom: 32px; }
.turn-marker {
  display: flex;
  justify-content: center;
  margin: 6px 0 20px;
  -webkit-user-select: none;
  user-select: none;
}
.turn-marker span {
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 4px 10px;
  -webkit-user-select: none;
  user-select: none;
}
.turn-chat {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
  max-width: 640px;
  margin: 0 auto;
}
.chat-row {
  display: grid;
  grid-template-columns: 36px minmax(0, 1fr);
  gap: 8px;
  align-items: start;
  width: 100%;
}
.chat-row.thinking-row-no-avatar > *,
.chat-row.assistant-row-no-avatar > *,
.chat-row.tool-row > * {
  grid-column: 2;
}
.chat-row.user {
  grid-template-columns: minmax(0, 1fr) 36px;
}
.chat-row.user > .avatar {
  grid-column: 2;
  grid-row: 1;
}
.chat-row.user > .bubble {
  grid-column: 1;
  grid-row: 1;
}
.avatar {
  width: 36px;
  height: 36px;
  border-radius: 6px;
  display: grid;
  place-items: center;
  font-size: 10px;
  font-weight: 600;
  flex: none;
}
.chat-row.user .avatar {
  background: var(--user-bg);
  color: var(--user-text);
  border: 1px solid var(--user-border);
}
.chat-row.assistant .avatar {
  background: var(--assistant-bg);
  color: var(--assistant-text);
  border: 1px solid var(--assistant-border);
}
.bubble,
.thinking-panel,
.tool-card {
  min-width: 0;
  border-radius: 10px;
  box-shadow: var(--shadow);
  overflow: hidden;
}
.bubble.assistant,
.thinking-panel,
.tool-card {
  width: var(--assistant-content-width);
  max-width: 100%;
}
.bubble.user {
  width: fit-content;
  max-width: min(var(--user-content-max), 100%);
  justify-self: end;
  background: var(--user-bg);
  color: var(--user-text);
  border: 1px solid var(--user-border);
}
.bubble.assistant {
  background: var(--assistant-bg);
  color: var(--assistant-text);
  border: 1px solid var(--assistant-border);
}
.bubble-body {
  padding: 8px 12px;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  line-height: 1.55;
}
.thinking-panel {
  background: var(--thinking-bg);
  border: 1px solid var(--thinking-border);
  border-radius: 12px;
}
.thinking-body {
  border-top: 1px solid var(--line);
  color: var(--thinking-text);
  font-style: normal;
}
.tool-card {
  border-radius: 12px;
  background: var(--panel);
}
.tool-card.call { border: 1px solid var(--tool-call-border); }
.tool-card.result.ok { border: 1px solid var(--tool-ok-border); }
.tool-card.result.fail { border: 1px solid var(--tool-fail-border); }
.tool-head {
  background: #fcfdfe;
}
.tool-card[open] > .tool-head {
  border-bottom: 1px solid var(--line);
}
.tool-badge {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #94a3b8;
}
.tool-name {
  font-size: 13px;
  font-weight: 600;
  color: #334155;
}
.tool-id {
  margin-left: auto;
  font-size: 11px;
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.tool-label {
  padding: 8px 14px 0;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--muted);
}
.tool-meta {
  padding: 8px 14px 0;
  font-size: 11px;
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.tool-code.stdout { color: #166534; }
.tool-code.stderr { color: #991b1b; }
.empty { color: var(--muted); text-align: center; padding: 40px 0; }
body.has-scrubber { padding-left: 64px; }
.scrubber {
  position: fixed;
  left: 24px;
  top: 72px;
  bottom: 24px;
  width: 22px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  z-index: 100;
  padding: 0;
  margin: 0;
}
.scrub-seg {
  flex: 1 1 0;
  min-height: 12px;
  border: none;
  padding: 0;
  margin: 0;
  cursor: pointer;
  border-radius: 5px;
  opacity: 0.55;
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.scrub-seg:hover,
.scrub-seg:focus-visible {
  opacity: 1;
  transform: scaleX(1.25);
  outline: none;
}
.scrub-seg.user { background: var(--user-bg); }
.scrub-seg.assistant { background: var(--assistant-bg); }
.scrub-seg.tool { background: #94a3b8; }
.scrub-seg.system { background: #cbd5e1; }
@media (max-width: 700px) {
  body.has-scrubber { padding-left: 0; }
  .scrubber { display: none; }
}
"""

TRACE_SCRUBBER_SCRIPT = """
document.querySelector(".scrubber")?.addEventListener("click", (event) => {
  const button = event.target.closest(".scrub-seg");
  if (!button) return;
  const target = document.getElementById(button.dataset.target);
  target?.scrollIntoView({ behavior: "smooth", block: "start" });
});
"""


def render_html(messages: Messages, *, title: str) -> str:
    all_messages = messages.data
    msg_index = 0
    assistant_avatar_shown = False
    turn_blocks: list[str] = []
    for turn_id, turn_messages in group_by_turn(messages):
        block, assistant_avatar_shown = render_turn_html(
            turn_id,
            turn_messages,
            msg_index,
            assistant_avatar_shown=assistant_avatar_shown,
        )
        turn_blocks.append(block)
        msg_index += len(turn_messages)

    body = "\n".join(turn_blocks) if turn_blocks else '<p class="empty">empty trace</p>'
    scrubber = render_scrubber(all_messages)
    body_attr = ' class="has-scrubber"' if scrubber else ""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)}</title>
  <style>{TRACE_STYLES}</style>
</head>
<body{body_attr}>
  {scrubber}
  <main>
    <h1 class="page-title">{esc(title)}</h1>
    {body}
  </main>
  <script>{TRACE_SCRUBBER_SCRIPT}</script>
</body>
</html>
"""


def trace_title(source: str) -> str:
    if source == "-":
        return "pagent trace (stdin)"
    try:
        return f"pagent trace · {resolve_messages_path(source)}"
    except SystemExit:
        return f"pagent trace · {source}"


def write_trace(
    source: str,
    *,
    fmt: str = "html",
    output: Path | None = None,
    open_browser: bool = False,
) -> Path | None:
    messages = load_messages(source)
    title = trace_title(source)

    if fmt == "text":
        text = render_text(messages, title=title)
        if output is None:
            sys.stdout.write(text)
            return None
        output.write_text(text, encoding="utf-8")
        return output

    html_doc = render_html(messages, title=title)
    if output is None:
        output = Path("pagent-trace.html")
    output.write_text(html_doc, encoding="utf-8")
    if open_browser:
        webbrowser.open(output.resolve().as_uri())
    return output


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="pagent-trace",
        description="Visualize pagent messages.jsonl trajectories.",
    )
    parser.add_argument(
        "source",
        help="messages.jsonl path, thread id under .pagent/threads/, or - for stdin JSONL",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=("html", "text"),
        default="html",
        help="output format (default: html)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="write to file instead of stdout (html default: pagent-trace.html)",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="open generated HTML in the default browser",
    )
    args = parser.parse_args(argv)

    path = write_trace(
        args.source,
        fmt=args.format,
        output=args.output,
        open_browser=args.open and args.format == "html",
    )
    if path is not None and args.format == "html":
        print(path, file=sys.stderr)


if __name__ == "__main__":
    main()

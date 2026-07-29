from electromind import Message, Messages, Thread
from electromind.trace import (
    load_messages,
    render_html,
    render_text,
    resolve_messages_path,
    write_trace,
)


def sample_messages() -> Messages:
    messages = Messages()
    messages += Message.system("You are helpful.")
    messages += Message.user("hello", turn_id=1)
    messages += Message.assistant({"type": "thinking", "text": "plan"}, turn_id=1)
    messages += Message.assistant({"type": "text", "text": "hi there"}, turn_id=1)
    messages += Message.assistant(
        {
            "type": "function",
            "id": "call_1",
            "name": "echo",
            "arguments": '{"msg":"ping"}',
        },
        turn_id=1,
    )
    messages += Message.tool_result("call_1", "pong", turn_id=1)
    return messages


def test_render_text_groups_turns():
    text = render_text(sample_messages(), title="demo")
    assert "=== turn 1 ===" in text
    assert "[user/text]" in text
    assert "[assistant/thinking]" in text
    assert "[assistant/tool_call]" in text
    assert "[tool/tool_result]" in text
    assert "hello" in text
    assert "pong" in text


def test_render_html_contains_roles():
    html_doc = render_html(sample_messages(), title="demo")
    assert 'class="bubble user"' in html_doc
    assert 'class="thinking-panel"' in html_doc
    assert '<details class="tool-card call">' in html_doc
    assert '<details class="tool-card result ok">' in html_doc
    assert '<div class="avatar">U</div>' in html_doc
    assert '<div class="avatar">A</div>' in html_doc
    assert "--assistant-content-width" in html_doc
    assert "--assistant-header-min-height" in html_doc
    assert "--assistant-header-pad" in html_doc
    assert ".thinking-panel > summary" in html_doc
    assert ".tool-card > summary" in html_doc
    assert "min-height: var(--assistant-header-min-height)" in html_doc
    assert "--user-content-max" in html_doc
    assert 'class="scrubber"' in html_doc
    assert 'id="msg-0"' in html_doc
    assert 'id="turn-1"' in html_doc
    assert 'data-target="msg-1"' in html_doc
    assert "scrollIntoView" in html_doc
    assert "hi there" in html_doc
    assert "pong" in html_doc


def test_first_thinking_gets_assistant_avatar():
    html_doc = render_html(sample_messages(), title="demo")
    assert 'id="msg-2"' in html_doc
    idx = html_doc.index('id="msg-2"')
    chunk = html_doc[max(0, idx - 80) : idx + 200]
    assert 'class="chat-row assistant thinking-row"' in chunk
    assert "thinking-row-no-avatar" not in chunk.split("thinking-panel", 1)[0]
    assert '<div class="avatar">A</div>' in chunk


def test_assistant_streak_shows_avatar_once():
    html_doc = render_html(sample_messages(), title="demo")
    turn_chat = html_doc.split('<div class="turn-chat">', 1)[1].split("</section>", 1)[
        0
    ]
    assert turn_chat.count('<div class="avatar">A</div>') == 1
    assert "assistant-row-no-avatar" in turn_chat


def test_text_first_gets_avatar_thinking_after_does_not():
    messages = Messages()
    messages += Message.user("go", turn_id=1)
    messages += Message.assistant({"type": "text", "text": "answer"}, turn_id=1)
    messages += Message.assistant({"type": "thinking", "text": "more"}, turn_id=1)
    html_doc = render_html(messages, title="demo")
    turn_chat = html_doc.split('<div class="turn-chat">', 1)[1].split("</section>", 1)[
        0
    ]
    assert turn_chat.count('<div class="avatar">A</div>') == 1
    assert "thinking-row-no-avatar" in turn_chat


def test_write_trace_html_file(tmp_path):
    messages = sample_messages()
    path = tmp_path / "messages.jsonl"
    messages.save_to_jsonl(path)

    out = write_trace(str(path), fmt="html", output=tmp_path / "out.html")
    assert out is not None
    content = out.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in content
    assert "hello" in content


def test_write_trace_text_stdout(capsys, tmp_path):
    messages = sample_messages()
    path = tmp_path / "messages.jsonl"
    messages.save_to_jsonl(path)

    write_trace(str(path), fmt="text", output=None)
    captured = capsys.readouterr().out
    assert "=== turn 1 ===" in captured


def test_load_messages_from_thread_id(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    messages = Messages()
    messages += Message.user("ping", turn_id=1)
    thread = Thread.open("viz-demo", overrides={"backend": "none"})
    messages.save_to_jsonl(thread.messages_storage_path)

    assert resolve_messages_path("viz-demo") == thread.messages_storage_path
    loaded = load_messages("viz-demo")
    assert loaded.data[-1].content.text == "ping"

from pagentv4 import Message, Messages


def test_messages_jsonl_round_trip(tmp_path):
    messages = Messages()
    messages += Message.system("You are helpful.", message_id="m-system")
    messages += Message.user("hello", turn_id=1)
    messages += Message.assistant(
        {"type": "thinking", "text": "let me think"}, turn_id=1
    )
    messages += Message.assistant({"type": "text", "text": "done"}, turn_id=1)
    messages += Message.assistant(
        {
            "type": "function",
            "id": "call_1",
            "name": "search",
            "arguments": '{"q":"x"}',
        },
        turn_id=1,
    )
    messages += Message.tool_result("call_1", "ok", turn_id=1)

    path = tmp_path / "messages.jsonl"
    messages.save_to_jsonl(path)

    restored = Messages.load_from_jsonl(path)

    assert restored == messages
    assert restored.data[0].message_id == "m-system"
    assert restored.data[0].turn_id == 0
    assert restored.data[1].turn_id == 1
    assert all(message.message_id for message in restored.data)
    assert path.read_text(encoding="utf-8").count("\n") == len(messages)


def test_to_openai_reasoning_only_assistant_uses_empty_content():
    messages = Messages()
    messages += Message.assistant({"type": "thinking", "text": "plan only"})
    api = messages.to_openai()
    assert api == [
        {"role": "assistant", "content": "", "reasoning_content": "plan only"}
    ]


def test_to_openai_tool_calls_may_keep_null_content():
    messages = Messages()
    messages += Message.assistant(
        {
            "type": "function",
            "id": "call_1",
            "name": "echo",
            "arguments": "{}",
        }
    )
    api = messages.to_openai()
    assert api[0]["content"] is None
    assert api[0]["tool_calls"][0]["id"] == "call_1"

import json

import pytest
import tiktoken

from pagent import (
    BACKEND_HUGGINGFACE,
    BACKEND_TIKTOKEN,
    count_tokens,
    count_tokens_detail,
    get_encoder,
    message_tokens,
    tools_tokens,
)
from pagent.tokens import TokenBreakdown, format_context, infer_backend


def test_message_tokens_user_content():
    msg = {"role": "user", "content": "hello world"}
    enc = tiktoken.encoding_for_model("gpt-4o")
    assert message_tokens(msg) == len(enc.encode("hello world"))


def test_message_tokens_multimodal_text_parts():
    msg = {
        "role": "user",
        "content": [
            {"type": "text", "text": "see "},
            {"type": "image_url", "image_url": {"url": "http://x"}},
            {"type": "text", "text": "this"},
        ],
    }
    enc = tiktoken.encoding_for_model("gpt-4o")
    assert message_tokens(msg) == len(enc.encode("see ")) + len(enc.encode("this"))


def test_message_tokens_assistant_tool_calls():
    args = '{"a": 1}'
    msg = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "add", "arguments": args},
            }
        ],
    }
    enc = tiktoken.encoding_for_model("gpt-4o")
    assert message_tokens(msg) == len(enc.encode("add")) + len(enc.encode(args))


def test_message_tokens_reasoning_content():
    msg = {"role": "assistant", "content": "ok", "reasoning_content": "think hard"}
    enc = tiktoken.encoding_for_model("gpt-4o")
    assert message_tokens(msg) == len(enc.encode("ok")) + len(enc.encode("think hard"))


def test_message_tokens_tool_message():
    msg = {"role": "tool", "tool_call_id": "call_1", "content": "result body"}
    enc = tiktoken.encoding_for_model("gpt-4o")
    assert message_tokens(msg) == len(enc.encode("result body")) + len(
        enc.encode("call_1")
    )


def test_count_tokens_agent_shaped_conversation():
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "weather?"},
        {
            "role": "assistant",
            "content": None,
            "reasoning_content": "need tool",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "web_search", "arguments": '{"q":"paris"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "sunny"},
        {"role": "assistant", "content": "It is sunny."},
    ]
    assert count_tokens(messages) == sum(message_tokens(m) for m in messages)


def test_tool_calls_dict_arguments():
    args = {"q": "paris"}
    msg = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "search", "arguments": args},
            }
        ],
    }
    enc = tiktoken.encoding_for_model("gpt-4o")
    expected = len(enc.encode("search")) + len(
        enc.encode(json.dumps(args, ensure_ascii=False))
    )
    assert message_tokens(msg) == expected


def test_count_tokens_detail_system_and_conversation():
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "tool", "tool_call_id": "c1", "content": "ok"},
    ]
    detail = count_tokens_detail(messages)
    enc = tiktoken.encoding_for_model("gpt-4o")
    assert detail.system == len(enc.encode("You are helpful."))
    assert detail.conversation == (
        len(enc.encode("hi"))
        + len(enc.encode("hello"))
        + len(enc.encode("ok"))
        + len(enc.encode("c1"))
    )
    assert detail.tools == 0
    assert detail.extras == {}
    assert detail.total == detail.system + detail.conversation


def test_count_tokens_detail_tools():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "search",
                "description": "Search the web",
                "parameters": {
                    "type": "object",
                    "properties": {"q": {"type": "string"}},
                },
            },
        }
    ]
    messages = [{"role": "user", "content": "go"}]
    detail = count_tokens_detail(messages, tools=tools)
    assert detail.tools == tools_tokens(tools)
    assert detail.total == detail.system + detail.tools + detail.conversation


def test_count_tokens_detail_extras():
    messages = [{"role": "user", "content": "x"}]
    extras = {"rules": "always be kind", "skills": "calendar"}
    detail = count_tokens_detail(messages, extras=extras)
    enc = tiktoken.encoding_for_model("gpt-4o")
    assert detail.extras == {
        "rules": len(enc.encode("always be kind")),
        "skills": len(enc.encode("calendar")),
    }
    assert detail.total == detail.conversation + sum(detail.extras.values())


def test_count_tokens_detail_total_is_sum_of_parts():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]
    tools = [{"type": "function", "function": {"name": "f", "parameters": {}}}]
    extras = {"rules": "r"}
    detail = count_tokens_detail(messages, tools=tools, extras=extras, max_tokens=1000)
    assert detail.total == detail.system + detail.tools + detail.conversation + sum(
        detail.extras.values()
    )
    assert detail.percent == 100.0 * detail.total / 1000
    assert detail.is_full is (detail.total >= 1000)


def test_get_encoder_tiktoken():
    enc = get_encoder(model="gpt-4o", backend=BACKEND_TIKTOKEN)
    ref = tiktoken.encoding_for_model("gpt-4o")
    text = "hello world"
    assert len(enc.encode(text)) == len(ref.encode(text))


def test_infer_backend_deepseek():
    assert infer_backend("deepseek-chat") == BACKEND_HUGGINGFACE
    assert infer_backend("gpt-4o") == BACKEND_TIKTOKEN
    assert infer_backend("o3-mini") == BACKEND_TIKTOKEN


def test_get_encoder_huggingface_smoke():
    pytest.importorskip("transformers")
    enc = get_encoder(backend=BACKEND_HUGGINGFACE, tokenizer="gpt2")
    assert len(enc.encode("hello")) > 0


def test_format_context_shows_buckets_and_counts():
    detail = TokenBreakdown(
        system=1200,
        tools=3400,
        conversation=8000,
        extras={"rules": 500, "skills": 300},
        total=13400,
        max_tokens=128_000,
    )
    out = format_context(detail, use_color=False)
    assert "Context" in out
    assert "10% Full" in out
    assert "~13.4K / 128K Tokens" in out
    assert "System prompt" in out
    assert "Tool definitions" in out
    assert "Rules" in out
    assert "Skills" in out
    assert "Conversation" in out
    assert "1.2K" in out
    assert "3.4K" in out
    assert "8K" in out
    assert "█" in out
    assert "■" in out


def test_format_context_without_max_tokens():
    detail = TokenBreakdown(
        system=42,
        tools=0,
        conversation=100,
        extras={},
        total=142,
        max_tokens=None,
    )
    out = format_context(detail, use_color=False)
    assert "142 Tokens" in out
    assert "% Full" not in out
    assert "System prompt" in out
    assert "Conversation" in out

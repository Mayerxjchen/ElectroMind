"""electromind.core.tool 的单测 —— 覆盖 call/acall 分支与 schema 提取。"""

from __future__ import annotations

import asyncio

from electromind.core.tool import (
    FunctionTool,
    ToolOutput,
    extract_function_schema,
    normalize_tool_output,
    to_openai_tools,
    tool,
    unwrap_optional,
)

# ---------------------------------------------------------------------------
# 同步 call：各种入参形态
# ---------------------------------------------------------------------------


@tool()
def add(a: int, b: int) -> int:
    """Add two numbers.

    Args:
        a: First.
        b: Second.
    """
    return a + b


def test_call_json_string():
    out = add.call('{"a": 2, "b": 3}')
    assert out.ok is True
    assert out.content == "5"


def test_call_dict_arguments():
    out = add.call({"a": 1, "b": 1})
    assert out.ok is True
    assert out.content == "2"


def test_call_none_arguments_calls_with_no_args():
    out = add.call(None)
    # add 缺参数会抛 TypeError，被 catch 成 fail
    assert out.ok is False
    assert "add error" in out.content


def test_call_empty_string_treated_as_no_args():
    out = add.call("   ")
    assert out.ok is False
    assert "add error" in out.content


def test_call_invalid_json():
    out = add.call("{not json")
    assert out.ok is False
    assert "Invalid JSON" in out.content


def test_call_no_bound_function():
    ft = FunctionTool("x", "", {"type": "object", "properties": {}})
    out = ft.call()
    assert out.ok is False
    assert "no bound function" in out.content


def test_call_async_func_rejected_in_sync_path():
    @tool()
    async def slow():
        """slow."""
        return "x"

    out = slow.call()
    assert out.ok is False
    assert "is async; use acall() instead" in out.content


def test_call_catches_exception():
    @tool()
    def boom():
        """boom."""
        raise RuntimeError("kaboom")

    out = boom.call("{}")
    assert out.ok is False
    assert "kaboom" in out.content


def test_call_func_that_takes_no_args():
    @tool()
    def ping():
        """ping."""
        return "pong"

    assert ping.call().content == "pong"
    assert ping.call(None).content == "pong"
    assert ping.call("").content == "pong"


# ---------------------------------------------------------------------------
# 异步 acall
# ---------------------------------------------------------------------------


@tool()
async def aadd(a: int, b: int) -> int:
    """Async add.

    Args:
        a: First.
        b: Second.
    """
    return a + b


def test_acall_json_string():
    out = asyncio.run(aadd.acall('{"a": 2, "b": 3}'))
    assert out.ok is True
    assert out.content == "5"


def test_acall_dict_arguments():
    out = asyncio.run(aadd.acall({"a": 1, "b": 1}))
    assert out.ok is True
    assert out.content == "2"


def test_acall_none_arguments():
    out = asyncio.run(aadd.acall(None))
    assert out.ok is False
    assert "aadd error" in out.content


def test_acall_empty_string():
    out = asyncio.run(aadd.acall("   "))
    assert out.ok is False
    assert "aadd error" in out.content


def test_acall_invalid_json():
    out = asyncio.run(aadd.acall("{bad"))
    assert out.ok is False
    assert "Invalid JSON" in out.content


def test_acall_no_bound_function():
    ft = FunctionTool("x", "", {"type": "object", "properties": {}})
    out = asyncio.run(ft.acall())
    assert out.ok is False
    assert "no bound function" in out.content


def test_acall_returns_sync_value():
    @tool()
    def sync_fn(x: int) -> int:
        """sync.

        Args:
            x: in.
        """
        return x * 2

    out = asyncio.run(sync_fn.acall('{"x": 5}'))
    assert out.ok is True
    assert out.content == "10"


def test_acall_catches_exception():
    @tool()
    async def boom():
        """boom."""
        raise ValueError("nope")

    out = asyncio.run(boom.acall())
    assert out.ok is False
    assert "nope" in out.content


# ---------------------------------------------------------------------------
# ToolOutput / normalize_tool_output
# ---------------------------------------------------------------------------


def test_tool_output_succeed_and_fail():
    ok = ToolOutput.succeed(123)
    assert ok.content == "123" and ok.ok is True
    bad = ToolOutput.fail("oops")
    assert bad.content == "oops" and bad.ok is False


def test_normalize_passthrough_tool_output():
    src = ToolOutput.succeed("x")
    assert normalize_tool_output(src) is src


def test_normalize_wraps_plain_value():
    out = normalize_tool_output("hello")
    assert isinstance(out, ToolOutput)
    assert out.content == "hello" and out.ok is True


# ---------------------------------------------------------------------------
# unwrap_optional
# ---------------------------------------------------------------------------


def test_unwrap_optional_non_union_returns_false():
    flag, base = unwrap_optional(int)
    assert flag is False
    assert base is int


def test_unwrap_optional_union_without_none():
    from typing import Union

    flag, base = unwrap_optional(Union[int, str])
    assert flag is False  # 没有 None 不当 optional


def test_unwrap_optional_single_none():
    flag, base = unwrap_optional(int | None)
    assert flag is True
    assert base is int


def test_unwrap_optional_multi_none_union():
    flag, base = unwrap_optional(int | str | None)
    assert flag is True
    # 多个非 None 类型归并成一个 Union
    from typing import get_args

    assert set(get_args(base)) == {int, str}


# ---------------------------------------------------------------------------
# type_to_schema（通过 extract_function_schema 间接覆盖各类型分支）
# ---------------------------------------------------------------------------


def test_schema_covers_basic_types():
    def fn(s: str, i: int, f: float, b: bool, lst: list[int]):
        """fn.

        Args:
            s: a string.
            i: an int.
            f: a float.
            b: a bool.
            lst: a list.
        """
        return None

    name, desc, schema = extract_function_schema(fn)
    assert name == "fn"
    assert desc == "fn."
    props = schema["properties"]
    assert props["s"] == {"type": "string", "description": "a string."}
    assert props["i"] == {"type": "integer", "description": "an int."}
    assert props["f"] == {"type": "number", "description": "a float."}
    assert props["b"] == {"type": "boolean", "description": "a bool."}
    assert props["lst"] == {
        "type": "array",
        "items": {"type": "integer"},
        "description": "a list.",
    }


def test_schema_optional_param_not_required():
    def fn(x: int, y: int | None = None):
        """fn.

        Args:
            x: required.
            y: optional.
        """
        return x

    _, _, schema = extract_function_schema(fn)
    assert schema["required"] == ["x"]


def test_schema_skips_context_param():
    def fn(context, x: int):
        """fn.

        Args:
            x: in.
        """
        return x

    _, _, schema = extract_function_schema(fn)
    assert "context" not in schema["properties"]
    assert list(schema["properties"]) == ["x"]


def test_schema_name_and_description_override():
    def fn(x: int):
        """orig."""
        return x

    name, desc, _ = extract_function_schema(
        fn, name_override="custom", description_override="override"
    )
    assert name == "custom"
    assert desc == "override"


def test_to_openai_tools_serializes():
    payload = to_openai_tools([add])
    assert payload == [
        {
            "type": "function",
            "function": {
                "name": "add",
                "description": "Add two numbers.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "a": {"type": "integer", "description": "First."},
                        "b": {"type": "integer", "description": "Second."},
                    },
                    "required": ["a", "b"],
                    "additionalProperties": False,
                },
            },
        }
    ]

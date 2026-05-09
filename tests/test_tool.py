import pytest

from pagent import FunctionTool, tool, to_openai_tools


@tool()
def add(a: int, b: int) -> int:
    """Add two numbers.

    Args:
        a: First.
        b: Second.
    """
    return a + b


def test_tool_call_json_string():
    assert add.call('{"a": 2, "b": 3}') == "5"


def test_tool_call_dict():
    assert add.call({"a": 1, "b": 1}) == "2"


def test_tool_call_invalid_json():
    out = add.call("{not json")
    assert "Invalid JSON" in out


def test_tool_no_func_errors():
    ft = FunctionTool("x", "", {"type": "object", "properties": {}})
    with pytest.raises(ValueError, match="no bound function"):
        ft.call()


def test_to_openai_tools():
    tools = to_openai_tools([add])
    assert len(tools) == 1
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["name"] == "add"
    assert "parameters" in tools[0]["function"]

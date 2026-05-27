from pagent import FunctionTool, to_openai_tools, tool


@tool()
def add(a: int, b: int) -> int:
    """Add two numbers.

    Args:
        a: First.
        b: Second.
    """
    return a + b


def test_tool_call_json_string():
    out = add.call('{"a": 2, "b": 3}')
    assert out.content == "5"
    assert out.ok is True


def test_tool_call_dict():
    out = add.call({"a": 1, "b": 1})
    assert out.content == "2"
    assert out.ok is True


def test_tool_call_invalid_json():
    out = add.call("{not json")
    assert out.ok is False
    assert "Invalid JSON" in out.content


def test_tool_no_func_errors():
    ft = FunctionTool("x", "", {"type": "object", "properties": {}})
    out = ft.call()
    assert out.ok is False
    assert "no bound function" in out.content


@tool()
def boom():
    raise RuntimeError("kaboom")


def test_tool_call_catches_exception():
    out = boom.call("{}")
    assert out.ok is False
    assert "kaboom" in out.content


def test_to_openai_tools():
    tools = to_openai_tools([add])
    assert len(tools) == 1
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["name"] == "add"
    assert "parameters" in tools[0]["function"]

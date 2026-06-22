# pagentv2 Tools

Tools in `pagentv2` are still ordinary Python functions decorated with
`@tool()`.

## Define a tool

```python
from pagentv2 import tool


@tool()
def get_weather(city: str) -> str:
    """Return weather for a city."""
    return f"Sunny in {city} today."
```

The decorator derives:

- tool name from the function name
- description from the docstring
- argument schema from type hints

## Use with `Agent`

```python
from pagentv2 import Agent, Provider

agent = Agent(
    Provider("gpt-4o-mini"),
    system="Use tools when needed.",
    tools=[get_weather],
)
```

## Tool outputs

Plain return values are wrapped into `ToolOutput(content=..., ok=True)`.

If you want to signal failure explicitly:

```python
from pagentv2 import ToolOutput, tool


@tool()
def calc(expression: str) -> ToolOutput:
    """Evaluate a simple arithmetic expression."""
    if not expression.strip():
        return ToolOutput.fail("empty expression")
    return ToolOutput.succeed("42")
```

`ToolResult.ok` is then exposed on the event stream.

## Argument handling

`FunctionTool.call()` accepts:

- `None`: call the tool with no arguments
- JSON string: parse then call with `**payload`
- mapping: call directly with `**arguments`

Invalid JSON is converted into a failed `ToolOutput`.

## Duplicate names

Tool names must be unique inside one `Agent`. Duplicate names raise
`ValueError` at construction time.

## Notes

- Keep docstrings short and concrete. The model sees them.
- Keep argument types simple unless you are sure the target model handles the
  resulting schema well.
- `pagentv2` currently models tool calls in the OpenAI function-call shape.

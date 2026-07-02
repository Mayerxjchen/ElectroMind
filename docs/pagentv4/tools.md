# pagentv4 Tools

语言：[中文](/zh/pagentv4/tools) | [English](/pagentv4/tools)

Tools in `pagentv4` are ordinary Python functions decorated with `@tool()`.
The `Runner` executes them during the multi-turn loop.

## Define a tool

```python
from pagentv4 import tool


@tool()
def get_weather(city: str) -> str:
    """Return weather for a city."""
    return f"Sunny in {city} today."
```

The decorator derives:

- tool name from the function name
- description from the docstring
- argument schema from type hints

## Use with `Agent` + `Runner`

```python
from pagentv4 import Agent, DeepSeek, Messages, Runner

agent = Agent(
    DeepSeek("deepseek-v4-flash"),
    system="Use tools when needed.",
    tools=[get_weather],
)
messages = Messages()

async for event in Runner().arun(agent, "Weather in Xiamen?", messages):
    ...
```

## Tool outputs

Plain return values are wrapped into `ToolOutput(content=..., ok=True)`.

To signal failure explicitly:

```python
from pagentv4 import ToolOutput, tool


@tool()
def calc(expression: str) -> ToolOutput:
    """Evaluate a simple arithmetic expression."""
    if not expression.strip():
        return ToolOutput.fail("empty expression")
    return ToolOutput.succeed("42")
```

`ToolResult.ok` is exposed on the event stream.

## Argument handling

`FunctionTool.call()` and `FunctionTool.acall()` accept:

- `None`: call the tool with no arguments
- JSON string: parse then call with `**payload`
- mapping: call directly with `**arguments`

Invalid JSON is converted into a failed `ToolOutput`.

`call()` is synchronous and only supports plain functions. Async tools must
use `acall()`; `Runner` does this automatically during a run.

## Async tools

```python
@tool()
async def fetch(city: str) -> str:
    """Fetch weather asynchronously."""
    return f"Sunny in {city}"
```

Register the tool on `Agent` as usual.

## Sandbox tools

When you use `Runner.session()` or bind a `Sandbox` manually, eight built-in
tools are available:

| Tool | Purpose |
|------|---------|
| `run_command` | Run a shell command in the workspace |
| `read_file` | Read a file |
| `write_file` | Write a file |
| `str_replace` | Replace text in a file |
| `list_dir` | List a directory |
| `list_host_files` | List files on the host side of the workspace |
| `copy_from_host` | Copy host file into the sandbox |
| `copy_to_host` | Copy sandbox file to the host |

Use `build_sandbox_tools(sandbox)` or `sandbox.tools()` to get them.
`Runner.session()` merges sandbox tools with any extra tools you pass.

## Skills

Skills are optional instruction packs loaded from `SKILL.md` directories.
Use `SkillRegistry.from_defaults()` and `make_use_skill_tool(registry)` to
let the model load skill instructions on demand. See `examples/v4runner/repl.py`.

## Notes

- Tool names must be unique inside one `Agent`.
- Keep docstrings short and concrete. The model sees them.
- Tool calls use the OpenAI function-call shape.

# pagentv4 工具

语言：[中文](/zh/pagentv4/tools) | [English](/pagentv4/tools)

`pagentv4` 的工具是普通 Python 函数，用 `@tool()` 装饰。
`Runner` 在多轮循环中执行它们。

## 定义工具

```python
from pagentv4 import tool


@tool()
def get_weather(city: str) -> str:
    """查询城市天气。"""
    return f"{city} 今天晴。"
```

装饰器会自动推导：

- 工具名：函数名
- 描述：docstring
- 参数 schema：类型注解

## 配合 `AgentCore` + `Runner`

```python
from pagentv4 import AgentCore, DeepSeek, Messages, Runner

agent = AgentCore(
    DeepSeek("deepseek-v4-flash"),
    system="需要时用工具。",
    tools=[get_weather],
)
messages = Messages()

async for event in Runner().arun(agent, "厦门天气怎么样？", messages):
    ...
```

## 工具返回值

普通返回值会包装成 `ToolOutput(content=..., ok=True)`。

显式表示失败：

```python
from pagentv4 import ToolOutput, tool


@tool()
def calc(expression: str) -> ToolOutput:
    """计算简单算术表达式。"""
    if not expression.strip():
        return ToolOutput.fail("表达式为空")
    return ToolOutput.succeed("42")
```

事件流上会暴露 `ToolResult.ok`。

## 参数处理

`FunctionTool.call()` 和 `FunctionTool.acall()` 接受：

- `None`：无参调用
- JSON 字符串：解析后 `**payload` 调用
- mapping：直接 `**arguments` 调用

无效 JSON 会转成失败的 `ToolOutput`。

`call()` 仅支持同步普通函数；async 工具须用 `acall()`，`Runner` 会自动处理。

## 异步工具

```python
@tool()
async def fetch(city: str) -> str:
    """异步查询天气。"""
    return f"{city} 今天晴"
```

照常注册到 `AgentCore` 即可。

## Sandbox 工具

使用 `Runner.create()` 并启用 sandbox 后，或手动绑定 `Sandbox` 时，有 8 个内置工具：

| 工具 | 作用 |
|------|------|
| `run_command` | 在工作目录执行 shell 命令 |
| `read_file` | 读文件 |
| `write_file` | 写文件 |
| `str_replace` | 替换文件中的文本 |
| `list_dir` | 列目录 |
| `list_host_files` | 列 workspace 宿主机侧文件 |
| `copy_from_host` | 从宿主机复制到 sandbox |
| `copy_to_host` | 从 sandbox 复制到宿主机 |

用 `build_sandbox_tools(sandbox)` 或 `sandbox.tools()` 获取。
`Runner.create()` 会把 sandbox 工具与你传入的额外工具合并。

## Skills

Skill 是从 `SKILL.md` 目录加载的可选指令包。
用 `SkillRegistry.from_defaults()` 和 `make_use_skill_tool(registry)` 让模型按需加载 skill 说明。
见 `examples/app/repl.py`。

## 注意

- 同一 `AgentCore` 内工具名必须唯一。
- docstring 要短而具体，模型会读到。
- 工具调用使用 OpenAI function-call 形态。

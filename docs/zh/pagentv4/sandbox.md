# pagentv4 Sandbox

语言：[中文](/zh/pagentv4/sandbox) | [English](/pagentv4/sandbox)

**sandbox** 是 agent 的伴身电脑：隔离的工作空间，可跑命令、读写文件。
各后端统一映射到虚拟 home（默认 `/home/agent`）。

## 快捷路径：`Runner.session()`

给 agent 配电脑的最简方式：

```python
from pagentv4 import DeepSeek, Runner

async for event in Runner().session(
    DeepSeek("deepseek-v4-flash"),
    "列出 /home/agent 下的文件，然后创建 notes.md。",
    workspace_id="default",
):
    ...
```

流程：

1. 按 `backend` / workspace 参数创建 sandbox
2. 绑定 sandbox 工具 + 额外工具
3. 构建 `Agent`，经 `Runner.arun()` 运行
4. 结束时关闭 sandbox（含异常路径）

## 后端

| `backend=` | 说明 |
|------------|------|
| `"local"` | 默认。宿主目录 `<cwd>/.pagent/workspaces/<id>/` |
| `"docker"` | 容器 + bind mount |
| `"podman"` | 同 docker，用 Podman CLI |
| `"ssh"` | 经 asyncssh 连远端 |

```python
async for event in Runner().session(
    provider,
    user_input,
    backend="docker",
    image="python:3.12-slim",
    workspace_id="demo",
):
    ...
```

SSH 示例：

```python
async for event in Runner().session(
    provider,
    user_input,
    backend="ssh",
    connection={"host": "user@example.com", "workdir": "/tmp/agent"},
):
    ...
```

## Workspace 布局

`workspace_id="default"` 时：

```text
<cwd>/.pagent/workspaces/default/
```

传 `workdir="/absolute/path"` 可覆盖。sandbox 把 agent 看到的 `/home/agent` 下路径映射到此目录。

## 直接使用 `Sandbox` API

需要更低层控制时：

```python
from pagentv4 import Sandbox

sandbox = await Sandbox.create(backend="local", workspace_id="my-project")
try:
    result = await sandbox.commands.run("ls -la")
    await sandbox.files.write("hello.txt", "hi")
    content = await sandbox.files.read_text("hello.txt")
finally:
    await sandbox.close()
```

上下文管理器写法：

```python
async with await Sandbox.create(backend="local", workspace_id="demo") as box:
    await box.files.write("hello.txt", "hi")
```

## 内置 agent 工具

`sandbox.tools()` 返回 8 个 `FunctionTool`（见 [工具](./tools)）。
展示给模型的措辞不含 "sandbox" 等内部术语。

## 与 Thread 集成

[Thread](./core-types#thread) 在 `.pagent/threads/<id>/` 下同时保存
sandbox spec、消息和 workspace。进程重启后仍要同一台电脑和同一段对话时用——见
`examples/v4runner/repl.py`。

## 资源限制

`sandbox.commands.run(..., timeout=...)` 和 `SandboxLimits` 限制 stdout、
stderr、内存和 CPU 时间。默认值偏保守，可按 workload 调整。

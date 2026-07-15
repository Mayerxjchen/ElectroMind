# pagentv4 Sandbox

语言：[中文](/zh/pagentv4/sandbox) | [English](/pagentv4/sandbox)

**sandbox** 是 agent 的伴身电脑：隔离的工作空间，可跑命令、读写文件。
各后端统一映射到虚拟 home（默认 `/home/agent`）。

## 快捷路径：`Runner.create()`

给 agent 配电脑的最简方式：

```python
from pagentv4 import DeepSeek, Runner

runner = await Runner.create(
    "demo",
    DeepSeek("deepseek-v4-flash"),
    overrides={"backend": "local"},
)
try:
    async for event in runner.run("列出 /home/agent 下的文件，然后创建 notes.md。"):
        ...
finally:
    await runner.close()
```

流程：

1. 打开 thread，并按 thread spec 创建 sandbox
2. 绑定 sandbox 工具 + 额外工具
3. 构建 `AgentCore`，经 `runner.run()` 运行
4. 用 `runner.close()` 关闭 sandbox

## 后端

| `backend=` | 说明 |
|------------|------|
| `"local"` | 默认。thread workspace 在 `~/.pagent/threads/<thread_id>/workspace/` |
| `"docker"` | 容器 + bind mount |
| `"podman"` | 同 docker，用 Podman CLI |
| `"ssh"` | 经 asyncssh 连远端 |

```python
runner = await Runner.create(
    "demo",
    provider,
    overrides={"backend": "docker", "image": "python:3.12-slim"},
)
try:
    async for event in runner.run(user_input):
        ...
finally:
    await runner.close()
```

SSH 示例，在 thread spec 或 overrides 里设置 `ssh_host`：

```python
runner = await Runner.create(
    "remote",
    provider,
    overrides={
        "backend": "ssh",
        "ssh_host": "user@example.com",
        "ssh_workdir": "/tmp/agent",
    },
)
```

## Workspace 布局

`thread_id="demo"` 时：

```text
~/.pagent/threads/demo/workspace/
```

持久化 runner 从 thread 获取 workspace。sandbox 把 agent 看到的 `/home/agent` 下路径映射到此目录。

## 直接使用 `Sandbox` API

需要更低层控制时，可以直接创建 sandbox，并自行选择 `workspace_id` 或 `workdir`：

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

[Thread](./core-types#thread) 在 `~/.pagent/threads/<id>/` 下同时保存
sandbox spec、消息和 workspace。进程重启后仍要同一台电脑和同一段对话时用——见
`examples/pagentv4/runner/sandbox.py`。

## 资源限制

`sandbox.commands.run(..., timeout=...)` 和 `SandboxLimits` 限制 stdout、
stderr、内存和 CPU 时间。默认值偏保守，可按 workload 调整。

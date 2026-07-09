# pagentv4 Sandbox

语言：[中文](/zh/pagentv4/sandbox) | [English](/pagentv4/sandbox)

A **sandbox** is the agent's companion computer: an isolated workspace where
it can run commands and read/write files. Paths are normalized to a virtual
home (default `/home/agent`) across all backends.

## Quick path: `Runner.create()`

The simplest way to give an agent a computer:

```python
from pagentv4 import DeepSeek, Runner

runner = await Runner.create(
    "demo",
    DeepSeek("deepseek-v4-flash"),
    overrides={"backend": "local"},
)
try:
    async for event in runner.run(
        "List files under /home/agent, then create notes.md."
    ):
        ...
finally:
    await runner.close()
```

Flow:

1. Open thread → create sandbox from thread spec
2. Bind sandbox tools + any extra tools passed to `create()`
3. Build `AgentCore` and run via `runner.run()`
4. Close sandbox with `runner.close()`

## Backends

| `backend=` | Notes |
|------------|-------|
| `"local"` | Default. Thread workspace on host under `.pagent/threads/<thread_id>/workspace/` |
| `"docker"` | Container with bind mount |
| `"podman"` | Same as docker, Podman CLI |
| `"ssh"` | Remote host via asyncssh |

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

SSH example — set `ssh_host` in thread spec or overrides:

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

## Workspace layout

With `thread_id="demo"`:

```text
<cwd>/.pagent/threads/demo/workspace/
```

Persistent runners get their workspace from the thread. The sandbox maps agent
paths under `/home/agent` to this directory.

## Direct `Sandbox` API

For lower-level control, you can create a sandbox directly and choose a
`workspace_id` or `workdir` yourself:

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

Context manager form:

```python
async with await Sandbox.create(backend="local", workspace_id="demo") as box:
    await box.files.write("hello.txt", "hi")
```

## Built-in agent tools

`sandbox.tools()` returns eight `FunctionTool` instances (see [Tools](./tools)).
Wording shown to the model avoids internal terms like "sandbox".

## Thread integration

A [Thread](./core-types#thread) stores sandbox spec, messages, and workspace
together under `.pagent/threads/<id>/`. Use this when you need the same
computer and conversation to survive across process restarts — see
`examples/pagentv4/runner/sandbox.py`.

## Limits

`sandbox.commands.run(..., timeout=...)` and `SandboxLimits` cap stdout,
stderr, memory, and CPU time. Defaults are conservative; tune per workload.

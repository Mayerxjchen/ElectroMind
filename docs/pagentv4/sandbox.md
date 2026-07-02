# pagentv4 Sandbox

语言：[中文](/zh/pagentv4/sandbox) | [English](/pagentv4/sandbox)

A **sandbox** is the agent's companion computer: an isolated workspace where
it can run commands and read/write files. Paths are normalized to a virtual
home (default `/home/agent`) across all backends.

## Quick path: `Runner.session()`

The simplest way to give an agent a computer:

```python
from pagentv4 import DeepSeek, Runner

async for event in Runner().session(
    DeepSeek("deepseek-v4-flash"),
    "List files under /home/agent, then create notes.md.",
    workspace_id="default",
):
    ...
```

Flow:

1. Create sandbox from `backend` / workspace params
2. Bind sandbox tools + any extra tools
3. Build `Agent` and run via `Runner.arun()`
4. Close sandbox when done (even on error)

## Backends

| `backend=` | Notes |
|------------|-------|
| `"local"` | Default. Workspace on host under `.pagent/workspaces/<id>/` |
| `"docker"` | Container with bind mount |
| `"podman"` | Same as docker, Podman CLI |
| `"ssh"` | Remote host via asyncssh |

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

SSH example:

```python
async for event in Runner().session(
    provider,
    user_input,
    backend="ssh",
    connection={"host": "user@example.com", "workdir": "/tmp/agent"},
):
    ...
```

## Workspace layout

With `workspace_id="default"`:

```text
<cwd>/.pagent/workspaces/default/
```

Pass `workdir="/absolute/path"` to override. The sandbox maps agent paths
under `/home/agent` to this directory.

## Direct `Sandbox` API

For lower-level control:

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
`examples/v4runner/repl.py`.

## Limits

`sandbox.commands.run(..., timeout=...)` and `SandboxLimits` cap stdout,
stderr, memory, and CPU time. Defaults are conservative; tune per workload.

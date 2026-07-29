# ElectroMind P0 Execution Modes Design

**Status:** Frozen for implementation planning  
**Date:** 2026-07-29

## Objective

Close the Local `workdir` command-policy escape by making execution capability
explicit and fail-closed:

- `workspace` provides controlled file tools and no arbitrary command execution.
- `sandbox` provides arbitrary command execution only inside Docker or Podman.
- `full-access` provides host command execution only after an exact, explicit
  user selection and displays a persistent danger warning.

The central security invariant is:

> Without an explicit `execution.mode = "full-access"`, ElectroMind can never
> resolve to a Local host shell.

## Scope

This P0 phase includes:

1. A centralized execution resolver as the single source of truth.
2. Explicit `workspace`, `sandbox`, and `full-access` modes.
3. Fail-closed legacy configuration migration.
4. Removal of `run_command` from the model's tool set in workspace mode.
5. Docker-first, Podman-second resolution for the `container` backend.
6. No fallback from sandbox mode to Local execution.
7. Structured policy-denial and execution-resolution errors.
8. Persistent CLI and Web/Desktop execution-state display.
9. Doctor checks derived from the same resolver.
10. Security and migration regression tests.

This phase does not include:

- macOS Seatbelt;
- dynamic filesystem grants or authorization dialogs;
- persistent directory grants;
- execution-mode switching within a running session;
- fine-grained network policy;
- a rewrite of Runner or Sandbox lifecycle architecture;
- a generalized capability framework beyond the fields needed here.

## Security Model

Planning, approval, capability resolution, and enforcement are separate:

```text
User request
  -> Agent selects a tool
  -> Capability/approval checks
  -> Execution backend enforces the resolved capability
  -> Result is verified, audited, and reported
```

Tool approval permits one proposed tool call. It does not expand filesystem
containment, enable an unregistered tool, select full-access, or weaken an
execution backend.

`command_policy="workdir"` remains, at most, a compatibility diagnostic or a
best-effort command check. It is not an isolation boundary and cannot enable
`run_command`.

## Responsibilities

```text
Config
  Parses explicit user input and legacy fields.

Execution Resolver
  Decides effective mode, backend, tools, warnings, and diagnostics.

Runner
  Registers only tools named by the resolved execution result.

Sandbox Factory
  Creates only the concrete backend selected by the resolver.

CLI / Wire / Web / Desktop
  Display the resolved result without inferring capabilities.

Doctor
  Uses the same resolver and runtime probe without starting a sandbox.
```

No consumer may independently decide:

- whether `run_command` is enabled;
- whether Local fallback is allowed;
- what missing execution configuration means;
- whether `container` resolves to Docker or Podman.

## Configuration

User intent is represented independently from backend implementation:

```toml
[execution]
mode = "workspace" # workspace | sandbox | full-access

[sandbox]
backend = "container" # container | docker | podman
```

CLI precedence is:

```text
explicit --execution-mode
  > explicit [execution].mode
  > workspace
```

Only the exact values `workspace`, `sandbox`, and `full-access` are accepted.
Aliases such as `open`, `local`, `host`, and `unrestricted` are invalid.

### Fail-closed legacy migration

If `[execution].mode` is absent, the result is always `workspace`, regardless
of legacy values:

```toml
backend = "local"
command_policy = "open"
```

or:

```toml
backend = "container"
```

Legacy fields may produce a diagnostic, but they never affect capability
resolution. ElectroMind does not rewrite the user's configuration.

An example diagnostic is:

```text
Legacy execution settings detected.

The previous backend and command_policy settings no longer enable host command
execution. ElectroMind is running in workspace mode with run_command disabled.

To intentionally enable host shell access, configure:

[execution]
mode = "full-access"
```

## Resolution Data Model

Configuration types express user input:

```python
@dataclass(frozen=True)
class ExecutionConfig:
    mode: Literal["workspace", "sandbox", "full-access"] | None


@dataclass(frozen=True)
class SandboxConfig:
    backend: Literal["container", "docker", "podman"] | None
```

The immutable resolved result is:

```python
@dataclass(frozen=True)
class ExecutionDiagnostic:
    code: str
    severity: Literal["info", "warning", "error"]
    message: str


@dataclass(frozen=True)
class ResolvedExecution:
    mode: Literal["workspace", "sandbox", "full-access"]
    requested_backend: Literal["container", "docker", "podman"] | None
    resolved_backend: Literal["docker", "podman", "local"] | None
    isolated: bool
    run_command_enabled: bool
    effective_tools: tuple[str, ...]
    warning: str | None
    diagnostics: tuple[ExecutionDiagnostic, ...]
```

The resolver interface is:

```python
def resolve_execution(
    config: ElectroMindConfig,
    *,
    runtime_probe: ContainerRuntimeProbe,
) -> ResolvedExecution:
    ...
```

`runtime_probe` is injected so tests can deterministically represent missing
commands, daemon failures, permission errors, timeouts, and usable runtimes.

The resolver may probe runtime availability. It must not start containers,
create sandboxes or runners, instantiate tools, contact model services, print
messages, or modify configuration.

## Mode Semantics

| Mode | Resolved backend | Isolated | `run_command` |
|---|---|---:|---:|
| `workspace` | `None` | No | Disabled |
| `sandbox` | `docker` or `podman` | Yes | Enabled |
| `full-access` | `local` | No | Enabled |

### Workspace

Workspace mode:

- creates no general command backend;
- never registers `run_command`;
- exposes only controlled workspace file tools;
- does not claim process isolation.

P0 reuses existing controlled file tools that already enforce workspace path
containment. New convenience tools such as `delete_paths` are separate,
test-driven additions and must not delay removal of `run_command`.

Workspace file operations must reject:

- `..` escape;
- absolute paths outside the workspace;
- target or parent symlink escape;
- deletion of the workspace root;
- empty paths and filesystem roots;
- unconfirmed recursive destructive operations.

### Sandbox

If sandbox mode omits a backend, the requested backend is `container`.

Resolution is deterministic:

1. Probe Docker.
2. If Docker is unusable, probe Podman.
3. If both are unusable, fail startup.

For explicit `backend="docker"`, only Docker is checked. For explicit
`backend="podman"`, only Podman is checked. Explicit or implicit
`backend="container"` uses the Docker-then-Podman sequence.

Runtime usability checks include executable discovery and a bounded service
probe such as `docker info` or `podman info`. Diagnostics distinguish:

- `container_runtime_unavailable`;
- `container_image_unavailable`;
- `sandbox_initialization_failed`.

The resolved backend is the concrete value `docker` or `podman`. No failure
path may create LocalBackend, workspace execution, or full-access execution.
`run_command` is registered only after the concrete isolated backend is
successfully initialized.

### Full-access

Full-access mode:

- requires exact, explicit configuration or CLI selection;
- resolves to LocalBackend;
- enables host `run_command`;
- retains normal tool-call approval semantics;
- displays a persistent danger warning in CLI and Web/Desktop UI.

The warning text must state:

```text
WARNING: FULL ACCESS
Commands run directly on the host with your current user permissions.
Workspace containment is not enforced.
```

`permission.mode=auto` is independent and can never select full-access.

## Runtime Probe

The probe reports per-runtime evidence rather than a Boolean:

```python
@dataclass(frozen=True)
class RuntimeProbeResult:
    runtime: Literal["docker", "podman"]
    usable: bool
    executable_found: bool
    service_reachable: bool
    error_code: str | None
    message: str
```

Probes have a fixed timeout and never initialize project containers. The
resolver preserves results as diagnostics so CLI, Doctor, Wire, and tests show
the same reason for a decision.

## Tool Registration and Backend Creation

Recommended call chain:

```python
config = load_config(...)
execution = resolve_execution(config, runtime_probe=runtime_probe)
backend = await create_execution_backend(execution, config=config)
runner = await open_runner(
    config,
    execution=execution,
    execution_backend=backend,
)
```

The resolver returns stable tool names, not concrete tool objects. Existing
tool-building code creates instances:

```python
tools = build_tools(
    execution.effective_tools,
    context=execution_context,
)
```

Runner may test membership in `effective_tools`; it may not inspect legacy
configuration to infer capability. Sandbox Factory accepts
`ResolvedExecution` and creates only its resolved backend.

## Structured Errors and Policy Denial

Resolution errors are structured:

```python
class ExecutionResolutionError(Exception):
    diagnostics: tuple[ExecutionDiagnostic, ...]


class InvalidExecutionModeError(ExecutionResolutionError):
    pass


class InvalidSandboxBackendError(ExecutionResolutionError):
    pass


class ContainerRuntimeUnavailableError(ExecutionResolutionError):
    pass
```

Resolver errors do not print. CLI and Wire translate them for their surfaces.

A policy denial returned to the Agent uses a machine-readable result:

```json
{
  "ok": false,
  "error_type": "policy_denied",
  "policy": "workspace_containment",
  "message": "The requested operation requires host shell access.",
  "recoverable_actions": [
    "use_sandbox_mode",
    "restart_in_full_access_mode",
    "use_workspace_file_tool"
  ]
}
```

`policy_denied` is authoritative. Fixed system instructions allow only:

- explaining the boundary;
- suggesting or requesting an authorized execution context;
- using an already registered, valid controlled tool;
- cancelling the step.

They forbid retrying the denied operation through scripts, interpreters,
encoded or dynamically assembled paths, environment variables, symlinks,
subprocesses, or alternate tools intended to evade the denial.

The execution layer remains authoritative: in workspace mode the general shell
tool is absent, so approval or model behavior cannot restore it.

## Status Surfaces

The backend publishes a serialized `ResolvedExecution` snapshot. Frontends
render it without capability inference:

```json
{
  "mode": "workspace",
  "requested_backend": null,
  "resolved_backend": null,
  "run_command_enabled": false,
  "isolated": false,
  "warning": null,
  "diagnostics": []
}
```

CLI and Web/Desktop continuously show:

- execution mode;
- requested and resolved backend when relevant;
- whether command execution is enabled;
- whether isolation is container-enforced;
- persistent full-access warning;
- fail-closed startup diagnostics.

Doctor invokes the same resolver and probe without creating a Sandbox:

```text
Execution configuration: sandbox
Docker executable found: yes
Docker daemon reachable: yes
Resolved backend: docker
Local fallback enabled: no
```

## Security Invariants

`validate_resolved_execution()` enforces:

```python
def validate_resolved_execution(value: ResolvedExecution) -> None:
    if value.mode == "workspace":
        assert value.resolved_backend is None
        assert not value.isolated
        assert not value.run_command_enabled
        assert "run_command" not in value.effective_tools

    elif value.mode == "sandbox":
        assert value.resolved_backend in {"docker", "podman"}
        assert value.isolated
        assert value.run_command_enabled
        assert "run_command" in value.effective_tools

    elif value.mode == "full-access":
        assert value.resolved_backend == "local"
        assert not value.isolated
        assert value.run_command_enabled
        assert "run_command" in value.effective_tools
        assert value.warning

    else:
        raise InvalidExecutionModeError(value.mode)
```

Additional invariants:

- absent execution configuration always resolves to workspace;
- legacy fields cannot change `run_command_enabled`;
- sandbox failure produces an error, never a downgraded result;
- permit cannot register or restore a disabled tool;
- frontend state is serialized from `ResolvedExecution`;
- no backend consumer contains a Local fallback from sandbox mode.

## Test Strategy

### Resolver and migration

- no execution configuration resolves to workspace;
- legacy Local plus `command_policy=open` resolves to workspace;
- legacy container configuration resolves to workspace;
- legacy fields never register `run_command`;
- only explicit full-access resolves to Local shell;
- invalid modes and sandbox backends fail;
- migration diagnostics explain ignored legacy fields;
- configuration files are not rewritten.

### Runtime resolution

- sandbox without a backend probes Docker first;
- usable Docker prevents a Podman probe;
- unusable Docker falls through to Podman;
- unusable Docker and Podman fail;
- explicit Docker never probes Podman;
- explicit Podman never probes Docker;
- explicit and implicit container behave identically;
- probe timeout and permission failures are diagnostic;
- resolved backend is included in status;
- container initialization failure never creates LocalBackend;
- `run_command` is registered only after isolated initialization.

### Tool and containment

- workspace tool set excludes `run_command`;
- permit cannot restore an absent `run_command`;
- Python, Shell, and Node scripts cannot be launched in workspace mode;
- workspace file tools reject paths and symlinks escaping the workspace;
- workspace root, empty path, and filesystem root cannot be deleted;
- recursive destructive tools require approval;
- the prior `clean_cache.py` bypass cannot occur because no shell tool exists.

### UI, CLI, Doctor, and protocol

- CLI displays mode and resolved backend;
- full-access warning remains visible throughout a CLI session;
- Wire sends the backend-generated execution snapshot;
- Web/Desktop displays the snapshot without inference;
- full-access warning remains visible in Web/Desktop;
- Doctor and startup produce the same resolution and diagnostics;
- sandbox startup failure reports that no Local fallback occurred.

### Agent behavior

- fixed instructions state that policy denial is authoritative;
- a policy denial exposes only authorized recovery actions;
- a denial does not cause the runtime to register alternate execution tools;
- destructive cache cleanup follows discover, confirm, execute, rescan, report.

An end-to-end container test verifies that a process can access the mounted
workspace but cannot see an unmounted host fixture.

## Rollout and Compatibility

This is an intentional security-breaking change for developers who previously
relied on Local `run_command`.

Upgrade behavior is fail-closed:

```text
Previous:
  backend = "local"
  command_policy = "workdir"

Resolved after upgrade:
  execution.mode = "workspace"
  run_command disabled
```

Developers who intentionally need a host shell must add:

```toml
[execution]
mode = "full-access"
```

Users who need isolated commands should use:

```toml
[execution]
mode = "sandbox"

[sandbox]
backend = "container"
```

Release notes, CLI migration diagnostics, Web/Desktop status, Doctor, and
configuration examples must describe this change. No migration code writes or
elevates user configuration.

## Acceptance Criteria

The P0 phase is complete only when:

1. `resolve_execution()` is the sole capability-resolution path.
2. Missing execution configuration resolves to workspace.
3. Workspace never exposes arbitrary command execution.
4. Sandbox executes only through a successfully initialized Docker or Podman
   backend and never falls back to Local.
5. Full-access is reachable only through explicit exact selection and displays
   a persistent warning.
6. Approval cannot expand execution capability.
7. CLI, Wire/Web/Desktop, and Doctor display the same resolved state.
8. Structured errors and migration diagnostics are covered by tests.
9. The former script-indirection bypass cannot be reproduced in workspace
   mode.

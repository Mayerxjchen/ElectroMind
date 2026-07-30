# Project Skills Auto-Discovery Design

## Status

Approved direction: project Skills are discovered and registered automatically. ElectroMind does not show a per-project or per-Skill trust prompt.

## Problem

ElectroMind currently treats `[agent].skills` frozen into `thread.toml` as the only runtime source. The active configuration points at `~/.electromind/skills`, while this repository's actual AICC Skill bundle lives at:

```text
<project>/skills/
├── AGENTS.md
├── procedures/*/SKILL.md
├── tools/*/SKILL.md
└── knowledge/*
```

The current loader scans only direct children of each configured root. It therefore does not discover the AICC bundle, does not load `skills/AGENTS.md`, and mounts every discovered Skill as an isolated directory. The filesystem browser can still show these files, which makes file visibility look like Skill availability even though the Runner has no `use_skill` registration.

Consequences:

- the Agent initially claims it has no Skills;
- a user must point out the directory manually;
- manually reading a `SKILL.md` is mistaken for runtime registration;
- AICC cross-references to `tools/`, `procedures/`, and `knowledge/` break after isolated mounting;
- HPC tasks fall back to generic SSH commands because `hpc-submit` and `rsess` were never disclosed;
- resumed threads can carry stale or empty Skill roots indefinitely.

## Goals

1. Automatically discover project and user Skills when a Runner opens.
2. Support the Agent Skills directory convention and the repository's AICC bundle layout.
3. Inject bundle-wide `AGENTS.md` routing rules before the Skill catalog.
4. Use progressive disclosure: metadata first, complete instructions and resources on activation.
5. Preserve the entire AICC bundle hierarchy in Local, Sandbox, and SSH execution modes.
6. Refresh changed Skills at user-turn boundaries without changing an active turn.
7. Make Skill availability, source, diagnostics, and activation version visible and auditable.
8. Keep Skill registration independent from tool approval and execution permissions.

## Non-goals

- No project trust dialog or persistent directory Grant.
- No keyword-based harness router that bypasses the model's Skill selection.
- No mid-turn hot swap of instructions or tools.
- No remote Skill marketplace, download, or automatic package installation.
- No change to Local, Sandbox, or SSH capability boundaries.
- No automatic execution of scripts merely because a Skill was registered.

## Discovery Sources

ElectroMind builds a deterministic source list whenever a Runner opens:

1. `<project>/skills` when it matches the AICC bundle shape.
2. `<project>/.agents/skills`.
3. `<project>/.electromind/skills`.
4. Explicit `[skills].roots` entries.
5. `~/.electromind/skills`.
6. `~/.agents/skills`.

The project directory is `ThreadSpec.project_path`, not process `cwd`. All paths are expanded and resolved before scanning.

### Standard source

A standard source contains direct children with `SKILL.md`:

```text
.agents/skills/
└── hpc-submit/
    ├── SKILL.md
    ├── references/
    └── scripts/
```

### AICC bundle source

An AICC source is recognized only when the root contains `AGENTS.md` and at least one of `procedures/` or `tools/`. Routable Skills are direct children of those two directories. `knowledge/` is shared reference material and is never registered as a Skill.

Hidden directories are ignored. A project source must not escape the resolved project root through `..` or a symbolic link. Malformed Skills are skipped with diagnostics; one malformed Skill does not hide valid siblings.

## Collision Policy

Skill names remain the public activation key. Sources are evaluated in the order above; the first valid occurrence wins. Later duplicates are not silently merged and are reported as `duplicate_skill_name` diagnostics containing both paths.

This makes project-specific workflows override user defaults while keeping behavior deterministic.

## Runtime Models

Introduce these immutable models:

```python
@dataclass(frozen=True, slots=True)
class SkillSource:
    id: str
    kind: Literal["aicc", "standard"]
    scope: Literal["project", "configured", "user"]
    root: Path
    priority: int

@dataclass(frozen=True, slots=True)
class SkillDiagnostic:
    code: str
    message: str
    path: str
    severity: Literal["warning", "error"]

@dataclass(frozen=True, slots=True)
class SkillMount:
    source_root: str
    skill_root: str
    bundle_root: str | None

@dataclass(frozen=True, slots=True)
class SkillCatalogSnapshot:
    registry: SkillRegistry
    sources: tuple[SkillSource, ...]
    global_instructions: tuple[str, ...]
    diagnostics: tuple[SkillDiagnostic, ...]
    fingerprint: str
```

Each `Skill` additionally records `source_id`, `skill_root`, optional `bundle_root`, and the SHA-256 of its `SKILL.md`.

## Progressive Disclosure

At Runner initialization, the model receives:

1. computer/execution description;
2. AICC `AGENTS.md` content from active bundles;
3. available Skill metadata: name, description, source, and activation instruction;
4. the application system tail.

The full `SKILL.md` body is returned only by `use_skill(name)`. Its result includes:

```json
{
  "ok": true,
  "name": "hpc-submit",
  "description": "...",
  "instructions": "...",
  "skill_root": "/home/agent/.skills/project-aicc/tools/hpc-submit",
  "bundle_root": "/home/agent/.skills/project-aicc",
  "resources": ["references/running.md", "scripts/..."],
  "sha256": "..."
}
```

The prompt explicitly requires the Agent to call `use_skill` before performing work that matches a description and prohibits claiming that no Skills exist without consulting the catalog.

## Bundle Mounting

Standard Skills are mounted beneath:

```text
<execution-home>/.skills/<source-id>/<skill-name>/
```

An AICC source is mounted once as a complete tree:

```text
<execution-home>/.skills/<source-id>/
├── AGENTS.md
├── procedures/
├── tools/
└── knowledge/
```

Every `SkillMount` points to both the individual Skill directory and its bundle root. Copying is content-addressed: unchanged source fingerprints are not recopied. Mounting uses backend file APIs for Local, Docker, Podman, and SSH and never calls a host shell.

## Refresh Semantics

Skill refresh happens at user-turn boundaries:

1. Before appending the next user message, rediscover sources and compute a catalog fingerprint.
2. If unchanged, continue without rebuilding anything.
3. If changed, rebuild the registry, update bundle mounts, rebuild the Skill prompt block, and replace the `use_skill` tool atomically.
4. Emit `SkillsState` with the new catalog and diagnostics.
5. Start the turn using the new immutable snapshot.

An active turn never observes a partial refresh. Adding, changing, or deleting a Skill becomes visible on the next user message. Resuming an existing thread rebuilds from its current `project_path`; it does not preserve a stale catalog.

Legacy `[agent].skills` entries remain accepted as explicit configured sources but are no longer the sole source of truth. ElectroMind does not rewrite existing `thread.toml` files.

## Agent Mutation API

`AgentCore` gains one atomic configuration method:

```python
def replace_runtime_context(
    self,
    *,
    system: str | None,
    tools: list[FunctionTool],
) -> None:
    ...
```

It rebuilds `tool_schemas` and `tool_map` with duplicate-name validation. Runner refresh also replaces the existing system message's generated Skill block before the next turn. Conversation history and user/assistant messages are unchanged.

Generated prompt sections use explicit markers so only ElectroMind-owned content is replaced:

```text
<!-- electromind:skills:start -->
...
<!-- electromind:skills:end -->
```

## Wire and UI

Replace the ambiguous `Skills` payload with `SkillsState`:

```json
{
  "thread_id": "thread-...",
  "fingerprint": "...",
  "skills": [
    {
      "name": "hpc-submit",
      "description": "...",
      "source": "project-aicc",
      "sha256": "..."
    }
  ],
  "diagnostics": []
}
```

It is emitted after Runner open, reset, resume, and catalog refresh. The existing `cmd:"skills"` remains as an explicit refresh/query operation.

Desktop UI labels are:

- **Available**: registered in the current catalog.
- **Loaded this task**: observed through a successful `use_skill` ToolResult.
- **Unavailable**: skipped with a diagnostic.

The UI never infers Skill availability from the project file tree.

## HPC Routing

Skill descriptions and bundle `AGENTS.md` own routing:

- scheduler submission, monitoring, recovery, or result gating → `hpc-submit`;
- Local execution controlling a remote host with persistent shell state → `rsess`, then `hpc-submit`;
- SSH execution mode → commands already execute on the remote target, so use `hpc-submit` directly and do not layer `rsess`;
- a simple connection probe may use `run_command`, but it must not be described as loading an HPC Skill.

`SshBackend` retains one AsyncSSH transport while each `run_command` creates an independent remote process. Documentation must distinguish transport persistence from shell-state persistence.

## Security Semantics

Per the approved product decision, project Skills are registered without a trust prompt. The UI and documentation state that binding a project makes its Skill instructions available to the Agent.

Registration does not grant capability:

- Skills cannot add tools.
- Skill frontmatter cannot pre-approve commands.
- Local/Sandbox/SSH resolution remains authoritative.
- Tool approval remains authoritative.
- File containment and backend policies remain authoritative.
- A denied operation cannot be retried through Skill scripts to bypass policy.

## Diagnostics

At minimum:

- `skill_source_missing`
- `invalid_skill_frontmatter`
- `missing_skill_description`
- `duplicate_skill_name`
- `project_skill_path_escape`
- `skill_mount_failed`
- `skill_refresh_failed`

Refresh is fail-closed per source snapshot: if a new snapshot cannot be mounted completely, the current turn keeps the previous valid snapshot and surfaces the error. It never exposes a half-built catalog.

## Required Tests

1. Project AICC bundle auto-discovery without configuration.
2. Standard `.agents/skills` project discovery.
3. User Skill discovery.
4. Project source wins duplicate names with a diagnostic.
5. `AGENTS.md` appears before Skill metadata.
6. `knowledge/`, `procedures/`, and `tools/` preserve bundle-relative paths.
7. Symlink and `..` project escapes are rejected.
8. Full instructions are absent from the initial prompt.
9. `use_skill` returns roots, resources, and SHA-256.
10. Resume rebuilds from the current project catalog.
11. Changed Skill appears on the next turn, not mid-turn.
12. Failed refresh retains the previous valid snapshot.
13. `SkillsState` is emitted for open/reset/resume/refresh.
14. Empty catalogs are reported explicitly.
15. Local/Sandbox/SSH mounting uses backend file APIs.
16. HPC catalog exposes `hpc-submit` and `rsess`.
17. SSH mode routing text says to use `hpc-submit` directly.
18. Skill registration never changes execution mode or approval state.

## Migration

- Existing `[skills].roots` values remain supported as explicit additional sources.
- Existing `[agent].skills` in old `thread.toml` files remain readable.
- New threads do not depend on frozen paths for project discovery.
- The old `Skills` Wire event is accepted by the desktop renderer for one compatibility release; the backend emits `SkillsState`.
- Documentation that says `{electromind_home}/skills` is the only default source is replaced with the complete discovery order.

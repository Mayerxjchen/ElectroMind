# Project Skills Auto-Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task by task. Use `test-driven-development` for every behavior change and `verification-before-completion` before claiming completion.

**Goal:** Make project Skills available automatically and truthfully in every new, resumed, or refreshed ElectroMind task, while preserving AICC bundle resources and routing HPC work through the correct Skill.

**Architecture:** Add one discovery/catalog layer between `ThreadSpec` and the existing `SkillRegistry`, make sandbox installation bundle-aware, and keep one immutable catalog snapshot per user turn. The Runner owns refresh; `AgentCore` only receives an atomic replacement of the generated Skill prompt and `use_skill` tool. Wire and desktop render catalog state emitted by the backend instead of inferring availability from visible files.

**Tech Stack:** Python 3.11+, dataclasses, PyYAML, asyncio, pytest, Ruff, Electron, TypeScript, esbuild.

## Global Constraints

- Work in an isolated Git worktree because the current checkout contains unrelated user changes.
- Do not change execution-mode resolution, approval behavior, or filesystem policy.
- Project Skills register directly; do not add a trust prompt.
- Skill registration never executes Skill scripts and never grants a tool permission.
- `ThreadSpec.project_path` is the project anchor. Never use process `cwd` for project discovery.
- Existing `[agent].skills` remains readable as additional legacy roots, but is no longer the sole source.
- Refresh only before a user turn. Never mutate tools or instructions during an active turn.
- A failed refresh retains the previous complete snapshot.
- Do not add keyword routing in the harness. Skill metadata and `skills/AGENTS.md` guide the model.
- Commit only files belonging to the task in each step.

---

## Task 1: Add deterministic Skill source discovery and catalog snapshots

**Files:**

- Create: `src/electromind/skills/discovery.py`
- Modify: `src/electromind/skills/skill.py`
- Modify: `src/electromind/skills/__init__.py`
- Test: `tests/test_pagentv4_skills.py`

### Step 1: Write failing discovery tests

Add fixtures for:

```text
project/
├── skills/
│   ├── AGENTS.md
│   ├── procedures/workflow/SKILL.md
│   ├── tools/hpc-submit/SKILL.md
│   └── knowledge/reference.md
└── .agents/skills/local-helper/SKILL.md
```

Cover:

```python
def test_discover_project_aicc_bundle_without_configuration(tmp_path): ...
def test_discover_standard_project_skills(tmp_path): ...
def test_project_skill_wins_duplicate_user_skill_with_diagnostic(tmp_path): ...
def test_aicc_knowledge_is_not_registered_as_skill(tmp_path): ...
def test_project_skill_symlink_escape_is_rejected(tmp_path): ...
def test_catalog_fingerprint_changes_when_skill_md_changes(tmp_path): ...
```

Assert the ordered source list:

1. `<project>/skills` when it has AICC shape;
2. `<project>/.agents/skills`;
3. `<project>/.electromind/skills`;
4. configured/legacy roots;
5. `~/.electromind/skills`;
6. `~/.agents/skills`.

Run:

```bash
uv run --group dev python -m pytest tests/test_pagentv4_skills.py -q
```

Expected: new tests fail because discovery models and AICC scanning do not exist.

### Step 2: Add immutable discovery models

In `src/electromind/skills/discovery.py`, add:

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
    severity: Literal["warning", "error"] = "warning"


@dataclass(frozen=True, slots=True)
class SkillMount:
    source_root: str
    skill_root: str
    bundle_root: str | None = None


@dataclass(frozen=True, slots=True)
class SkillCatalogSnapshot:
    registry: SkillRegistry
    sources: tuple[SkillSource, ...]
    global_instructions: tuple[str, ...]
    diagnostics: tuple[SkillDiagnostic, ...]
    fingerprint: str
```

Add public functions:

```python
def discover_skill_sources(
    project_path: str | Path | None,
    *,
    configured_roots: Sequence[str | Path] = (),
    user_home: Path | None = None,
) -> tuple[SkillSource, ...]: ...


def load_skill_catalog(
    sources: Sequence[SkillSource],
) -> SkillCatalogSnapshot: ...
```

Use stable source IDs derived from scope, kind, and normalized path. Hash source metadata, `AGENTS.md`, every registered `SKILL.md`, and resource-relative paths in deterministic order.

### Step 3: Extend `Skill` without breaking direct loaders

Extend `Skill` in `skill.py`:

```python
source_id: str = ""
skill_root: Path | None = None
bundle_root: Path | None = None
sha256: str = ""
```

Keep `root` temporarily as the compatibility alias for `skill_root`. Existing `load_skill()` and `SkillRegistry.from_dirs()` tests must continue to pass.

For AICC sources:

- read direct children of `procedures/` and `tools/`;
- load root `AGENTS.md` into `global_instructions`;
- preserve the AICC root as `bundle_root`;
- do not register `knowledge/`.

Catch malformed siblings individually and emit diagnostics. Resolve every candidate and verify it remains within its allowed source/project root.

### Step 4: Export the new API and verify

Export models and functions from `src/electromind/skills/__init__.py`.

Run:

```bash
uv run --group dev python -m pytest tests/test_pagentv4_skills.py -q
uv run ruff check src/electromind/skills tests/test_pagentv4_skills.py
```

Expected: all Skill tests pass and duplicate names are diagnostic, not an uncaught registry error.

### Step 5: Commit

```bash
git add src/electromind/skills tests/test_pagentv4_skills.py
git commit -m "feat: discover project skill catalogs"
```

---

## Task 2: Preserve complete bundles when installing Skills

**Files:**

- Modify: `src/electromind/sandbox/sandbox.py`
- Modify: `src/electromind/skills/discovery.py`
- Test: `tests/test_pagentv4_sandbox.py`

### Step 1: Write failing bundle-mount tests

Add:

```python
async def test_install_aicc_catalog_preserves_bundle_tree(tmp_path): ...
async def test_install_standard_skill_uses_source_and_skill_directory(tmp_path): ...
async def test_install_catalog_returns_skill_and_bundle_roots(tmp_path): ...
async def test_install_catalog_rejects_resource_symlink_escape(tmp_path): ...
async def test_unchanged_catalog_is_not_rewritten(tmp_path): ...
```

The AICC assertion must verify these execution-side files:

```text
<home>/.skills/<source-id>/AGENTS.md
<home>/.skills/<source-id>/tools/hpc-submit/SKILL.md
<home>/.skills/<source-id>/procedures/workflow/SKILL.md
<home>/.skills/<source-id>/knowledge/reference.md
```

Run:

```bash
uv run --group dev python -m pytest tests/test_pagentv4_sandbox.py -q
```

Expected: failures because `install_skills()` currently copies every Skill into an isolated `<name>/` directory.

### Step 2: Add catalog-aware installation

Add:

```python
async def install_skill_catalog(
    self,
    snapshot: SkillCatalogSnapshot,
) -> dict[str, SkillMount]: ...
```

Rules:

- Standard source target: `<home>/.skills/<source-id>/<skill-name>/`.
- AICC target: `<home>/.skills/<source-id>/`, copied once as a complete bundle.
- All writes use `self.files.write`; do not invoke Shell, Python, tar, or `cp`.
- Reject any resolved source file outside the declared source root.
- Return one `SkillMount` per public Skill name.
- Cache the last successfully installed fingerprint on the `Sandbox`; return its mounts without rewriting when unchanged.
- Update cache only after every source finishes successfully.

Keep `install_skills(registry)` as a compatibility wrapper for existing callers/tests during this task.

### Step 3: Verify all execution backends use the same file API path

Use fake backend/file-service tests to prove installation does not branch on Local, Docker, Podman, or SSH class names. Backend-specific behavior belongs below `Sandbox.files`.

Run:

```bash
uv run --group dev python -m pytest tests/test_pagentv4_sandbox.py -q
uv run ruff check src/electromind/sandbox/sandbox.py tests/test_pagentv4_sandbox.py
```

### Step 4: Commit

```bash
git add src/electromind/sandbox/sandbox.py src/electromind/skills/discovery.py tests/test_pagentv4_sandbox.py
git commit -m "feat: mount complete skill bundles"
```

---

## Task 3: Implement progressive disclosure and activation metadata

**Files:**

- Modify: `src/electromind/skills/skill.py`
- Test: `tests/test_pagentv4_skills.py`

### Step 1: Write failing prompt and activation tests

Add:

```python
def test_global_agents_instructions_precede_skill_catalog(tmp_path): ...
def test_initial_prompt_excludes_skill_body(tmp_path): ...
async def test_use_skill_returns_skill_and_bundle_roots(tmp_path): ...
async def test_use_skill_returns_resources_and_sha256(tmp_path): ...
async def test_use_skill_notifies_activation_observer(tmp_path): ...
```

The prompt must contain owned markers:

```text
<!-- electromind:skills:start -->
...
<!-- electromind:skills:end -->
```

The initial prompt may include name, description, source, and mounted root, but must not contain the `SKILL.md` instruction body.

### Step 2: Change prompt/tool inputs to catalog snapshots

Use signatures:

```python
def build_skills_system_prompt(
    snapshot: SkillCatalogSnapshot,
    mounts: Mapping[str, SkillMount] | None = None,
) -> str: ...


def make_use_skill_tool(
    snapshot: SkillCatalogSnapshot,
    mounts: Mapping[str, SkillMount] | None = None,
    *,
    on_activate: Callable[[Skill], None] | None = None,
) -> FunctionTool: ...
```

Successful `use_skill` returns:

```json
{
  "ok": true,
  "name": "hpc-submit",
  "description": "...",
  "instructions": "...",
  "skill_root": "...",
  "bundle_root": "...",
  "resources": ["..."],
  "sha256": "..."
}
```

Call `on_activate` only after a valid Skill has been found and the payload has been constructed.

Keep compatibility overloads for direct `SkillRegistry` callers until Task 5 migrates all runtime call sites.

### Step 3: Verify

```bash
uv run --group dev python -m pytest tests/test_pagentv4_skills.py -q
uv run ruff check src/electromind/skills/skill.py tests/test_pagentv4_skills.py
```

### Step 4: Commit

```bash
git add src/electromind/skills/skill.py tests/test_pagentv4_skills.py
git commit -m "feat: disclose skill instructions on demand"
```

---

## Task 4: Make project discovery the Runner source of truth

**Files:**

- Modify: `src/electromind/runtime/base_runner.py`
- Modify: `src/electromind/ithread/__init__.py`
- Modify: `src/app/config.py`
- Test: `tests/test_pagentv4_base_runner.py`
- Test: `tests/test_pagentv4_ithread.py`
- Test: `tests/test_app_config.py`

### Step 1: Write failing Runner assembly tests

Add:

```python
async def test_runner_discovers_project_skills_from_thread_project_path(tmp_path): ...
async def test_runner_treats_thread_skills_as_additional_legacy_roots(tmp_path): ...
async def test_runner_project_skill_overrides_legacy_duplicate(tmp_path): ...
async def test_runner_without_project_still_discovers_user_skills(tmp_path): ...
```

Assert that an empty `ThreadSpec.skills` no longer produces an empty catalog when `<project>/skills` exists.

### Step 2: Replace registry-only resource assembly

Extend `RunResources` with:

```python
catalog: SkillCatalogSnapshot
skill_mounts: dict[str, SkillMount]
```

Inside `assemble_run_resources()`:

1. derive sources from `thread.spec.project_path`;
2. append `thread.spec.skills` and programmatic `skill_roots` as configured sources;
3. load one snapshot;
4. install it through `sandbox.install_skill_catalog()` when a Sandbox exists;
5. register `use_skill` whenever the catalog is non-empty;
6. put global bundle instructions before Skill metadata.

Update the `ThreadSpec.skills` comment and config help text to say “additional roots / legacy compatibility,” not “唯一事实来源”.

Do not rewrite old `thread.toml`.

### Step 3: Verify migration behavior

Run:

```bash
uv run --group dev python -m pytest \
  tests/test_pagentv4_base_runner.py \
  tests/test_pagentv4_ithread.py \
  tests/test_app_config.py -q
uv run ruff check \
  src/electromind/runtime/base_runner.py \
  src/electromind/ithread/__init__.py \
  src/app/config.py
```

### Step 4: Commit

```bash
git add \
  src/electromind/runtime/base_runner.py \
  src/electromind/ithread/__init__.py \
  src/app/config.py \
  tests/test_pagentv4_base_runner.py \
  tests/test_pagentv4_ithread.py \
  tests/test_app_config.py
git commit -m "feat: bind project skills to runners"
```

---

## Task 5: Refresh Skills atomically at user-turn boundaries

**Files:**

- Create: `src/electromind/skills/runtime.py`
- Modify: `src/electromind/core/agent.py`
- Modify: `src/electromind/runtime/loop_adapter.py`
- Modify: `src/electromind/runtime/base_runner.py`
- Modify: `src/electromind/runtime/runner.py`
- Test: `tests/test_pagentv4_agent.py`
- Test: `tests/test_pagentv4_base_runner.py`

### Step 1: Write failing atomic-replacement tests

Add:

```python
def test_agent_replace_runtime_context_rebuilds_tool_schema_and_map(): ...
def test_agent_replace_runtime_context_rejects_duplicate_tools_atomically(): ...
async def test_skill_added_between_turns_is_available_next_turn(tmp_path): ...
async def test_skill_change_does_not_mutate_active_turn(tmp_path): ...
async def test_failed_refresh_keeps_previous_snapshot(tmp_path): ...
async def test_resume_rebuilds_catalog_from_current_project(tmp_path): ...
```

The duplicate test must assert that the old system, tools, schemas, and map remain unchanged after the exception.

### Step 2: Add the atomic Agent API

In `AgentCore`:

```python
def replace_runtime_context(
    self,
    *,
    system: str | None,
    tools: list[FunctionTool],
) -> None:
    schemas = to_openai_tools(tools) or None
    names = [tool.name for tool in tools]
    if len(names) != len(set(names)):
        raise ValueError(f"duplicate tool names: {names}")
    tool_map = {tool.name: tool for tool in tools}

    self.system = system
    self.tools = tools
    self.tool_schemas = schemas
    self.tool_map = tool_map
```

Build all replacement values before assigning them.

### Step 3: Add a pre-turn hook

In `LoopAdapter`:

```python
async def before_user_turn(self, user_input: str) -> None:
    del user_input
```

Call it in `run()` before `ensure_system()` and before appending the user message:

```python
await self.before_user_turn(user_input)
ensure_system(self.messages, self.agent.system)
```

### Step 4: Add `SkillRuntime`

`src/electromind/skills/runtime.py` owns:

- project/configured source inputs;
- current valid snapshot and mounts;
- generated Skill prompt block;
- activated Skill names for the current task;
- diagnostics callback.

Expose:

```python
async def refresh_if_changed(self) -> bool: ...
def build_use_skill_tool(self) -> FunctionTool: ...
def state_payload(self, *, thread_id: str) -> dict: ...
```

Refresh algorithm:

1. discover and load a candidate snapshot;
2. return `False` if fingerprint is unchanged;
3. install the complete candidate;
4. construct prompt and tool replacements;
5. call `AgentCore.replace_runtime_context`;
6. publish the new snapshot only after all earlier steps succeed.

On failure, keep the previous snapshot/mounts/tools and record `skill_refresh_failed`.

Replace only the marked ElectroMind Skill section in the system text. Do not edit user or assistant history.

### Step 5: Wire the Runner lifecycle

Have `BaseRunner.before_user_turn()` call `SkillRuntime.refresh_if_changed()`. Runner creation and resume both create the runtime from current `thread.spec.project_path`, so no stale frozen registry survives reopening.

### Step 6: Verify

```bash
uv run --group dev python -m pytest \
  tests/test_pagentv4_agent.py \
  tests/test_pagentv4_base_runner.py -q
uv run ruff check \
  src/electromind/core/agent.py \
  src/electromind/runtime \
  src/electromind/skills/runtime.py
```

### Step 7: Commit

```bash
git add \
  src/electromind/core/agent.py \
  src/electromind/runtime \
  src/electromind/skills/runtime.py \
  tests/test_pagentv4_agent.py \
  tests/test_pagentv4_base_runner.py
git commit -m "feat: refresh skills between user turns"
```

---

## Task 6: Emit truthful Skill state over Wire and render it in Desktop

**Files:**

- Modify: `src/app/wire.py`
- Modify: `editors/desktop/src/shared/protocol.ts`
- Modify: `editors/desktop/src/main/index.ts`
- Modify: `editors/desktop/src/renderer/main.ts`
- Modify: `editors/desktop/src/renderer/style.css`
- Test: `tests/test_app_wire_lazy.py`
- Create: `editors/desktop/scripts/skills-state.test.mjs`
- Modify: `editors/desktop/package.json`

### Step 1: Write failing Wire tests

Test `SkillsState` after:

- initial Runner open;
- successful reset;
- resume;
- changed catalog refresh;
- explicit `{cmd: "skills"}`;
- empty catalog.

Required payload:

```json
{
  "thread_id": "thread-id",
  "fingerprint": "sha256",
  "skills": [
    {
      "name": "hpc-submit",
      "description": "...",
      "source": "project-aicc",
      "sha256": "...",
      "status": "available"
    }
  ],
  "loaded": [],
  "diagnostics": []
}
```

Run:

```bash
uv run --group dev python -m pytest tests/test_app_wire_lazy.py -q
```

### Step 2: Replace backend emission

Replace `emit_skills(runner)` with `emit_skills_state(runner)`, delegating payload creation to `SkillRuntime.state_payload()`.

The backend emits only `SkillsState`. Keep desktop support for old `Skills` events for one compatibility release.

Emit refreshed state only at the same turn boundary where the new snapshot becomes active.

### Step 3: Add typed desktop normalization

In `protocol.ts`, define:

```ts
export interface SkillStateItem {
  name: string;
  description: string;
  source: string;
  sha256: string;
  status: "available" | "loaded" | "unavailable";
}

export interface SkillsStatePayload {
  thread_id: string;
  fingerprint: string;
  skills: SkillStateItem[];
  loaded: string[];
  diagnostics: SkillDiagnosticPayload[];
}
```

Normalize in the main process before passing it to the renderer. Ignore events whose `thread_id` is not the active task, matching the existing `ExecutionState` binding rule.

### Step 4: Update the Skills panel

Render sections:

- `可用` — registered catalog entries;
- `本任务已加载` — successful `use_skill` activations;
- `不可用` — diagnostics with source/path and concise reason.

Remove the current empty-state claim that only `~/.electromind/skills/` is scanned. Replace it with:

```text
当前项目和用户目录中未发现可用 Skill。
支持项目 skills/、.agents/skills、.electromind/skills。
```

Do not infer availability from the right-side project file tree.

### Step 5: Add renderer-state tests and verify

The Node test should cover:

- `SkillsState` replacing the catalog;
- old `Skills` compatibility normalization;
- stale thread event ignored;
- diagnostic-only empty state;
- loaded badge rendering.

Run:

```bash
uv run --group dev python -m pytest tests/test_app_wire_lazy.py -q
cd editors/desktop
npm run check
npm run compile
npm run test:skills-state
```

### Step 6: Commit

```bash
git add \
  src/app/wire.py \
  tests/test_app_wire_lazy.py \
  editors/desktop/src \
  editors/desktop/scripts/skills-state.test.mjs \
  editors/desktop/package.json
git commit -m "feat: show project skill catalog state"
```

---

## Task 7: Lock HPC routing and SSH semantics with regression tests

**Files:**

- Modify: `skills/AGENTS.md`
- Modify: `skills/README.md`
- Modify: `skills/tools/hpc-submit/SKILL.md`
- Modify: `skills/tools/rsess/SKILL.md`
- Modify: `src/electromind/sandbox/backends/ssh.py` (documentation only unless tests expose a code defect)
- Create: `tests/test_project_skill_autodiscovery.py`
- Modify: `README.md`
- Modify: `docs/architecture.md`

### Step 1: Write the end-to-end bundle test

Use the real repository Skill bundle and assert:

```python
def test_repository_bundle_registers_hpc_skills(): ...
def test_repository_bundle_loads_agents_before_catalog(): ...
def test_ssh_routing_uses_hpc_submit_without_rsess_layer(): ...
def test_local_remote_workflow_routes_rsess_then_hpc_submit(): ...
```

These are catalog/prompt contract tests, not model-output snapshot tests. Assert exact routing sentences from `skills/AGENTS.md` are present before the catalog.

### Step 2: Clarify routing documentation

Freeze these rules:

```text
scheduler submission/monitoring/recovery/result gating
→ hpc-submit

Local execution controlling a remote persistent shell
→ rsess, then hpc-submit

execution.mode=ssh
→ hpc-submit directly; do not open rsess inside SSH
```

Document that `SshBackend` may reuse one AsyncSSH transport, while each `run_command` is an independent remote process and does not preserve `cd`, exported variables, shell functions, or activated environments.

Do not describe a successful `hostname && whoami` probe as a loaded HPC Skill.

### Step 3: Update product documentation

Document:

- complete discovery order;
- direct project registration;
- progressive disclosure;
- registration versus permission boundary;
- turn-bound refresh;
- desktop status meanings;
- AICC bundle directory contract.

Remove statements that `~/.electromind/skills` is the only automatic source.

### Step 4: Verify

```bash
uv run --group dev python -m pytest tests/test_project_skill_autodiscovery.py -q
uv run ruff check tests/test_project_skill_autodiscovery.py
```

### Step 5: Commit

```bash
git add \
  skills \
  src/electromind/sandbox/backends/ssh.py \
  tests/test_project_skill_autodiscovery.py \
  README.md \
  docs/architecture.md
git commit -m "docs: define skill and HPC routing semantics"
```

---

## Task 8: Run full verification and manual desktop acceptance

**Files:**

- Modify only if verification finds a task-scoped defect.

### Step 1: Run focused Python tests

```bash
uv run --group dev python -m pytest \
  tests/test_pagentv4_skills.py \
  tests/test_pagentv4_sandbox.py \
  tests/test_pagentv4_agent.py \
  tests/test_pagentv4_base_runner.py \
  tests/test_app_wire_lazy.py \
  tests/test_project_skill_autodiscovery.py -q
```

### Step 2: Run full Python quality gates

```bash
uv run ruff check src tests
uv run --group dev python -m pytest -q
```

Record unrelated pre-existing failures separately; do not claim a fully green suite unless the command actually exits zero.

### Step 3: Run desktop quality gates

```bash
cd editors/desktop
npm run check
npm run compile
npm run test:skills-state
```

If the repository's normal CI entry point is available:

```bash
cd /path/to/worktree
bash scripts/ci-check.sh
```

### Step 4: Perform manual acceptance

From a clean project task:

1. Start ElectroMind with `project_path` set to the repository and no `[agent].skills`.
2. Open Skills panel before sending a message.
3. Confirm `hpc-submit`, `rsess`, procedures, and tools are available.
4. Confirm `knowledge/` is not shown as a Skill.
5. Ask “你现在有 skills 吗？” and confirm the Agent answers from the catalog without a path hint.
6. Ask it to inspect an HPC environment; confirm it calls `use_skill("hpc-submit")` in SSH mode.
7. Add a temporary Skill and send the next user message; confirm it appears without restarting.
8. Corrupt that temporary `SKILL.md`; confirm the previous valid catalog remains usable and the UI shows a diagnostic.
9. Resume another task and confirm Skill state switches by `thread_id`.
10. Confirm no execution mode or approval setting changed.

### Step 5: Review the final diff

```bash
git status --short
git diff --check
git log --oneline --decorate -8
```

Verify no unrelated files from the original dirty checkout entered the worktree commits.

### Step 6: Final integration commit only if needed

If verification required task-scoped fixes:

```bash
git add <only-task-files>
git commit -m "fix: close skill discovery integration gaps"
```

Otherwise do not create an empty commit.

## Completion Criteria

- A project AICC bundle registers without configuration or user prompting.
- Standard project and user Skill directories are discovered in deterministic order.
- Full Skill instructions are loaded only through `use_skill`.
- AICC cross-references remain valid in Local, Sandbox, and SSH modes.
- Skill changes appear on the next user turn; failed refresh retains the prior snapshot.
- Desktop reports backend-emitted availability, activation, and diagnostics for the active task.
- SSH/HPC work loads the appropriate Skill without requiring the user to point out the Skill directory.
- Registration cannot change execution capability or approval state.
- Focused tests, TypeScript checks, builds, and the final documented validation suite pass as reported.

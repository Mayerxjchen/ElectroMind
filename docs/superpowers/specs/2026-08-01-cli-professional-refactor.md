# ElectroMind CLI Professional Refactor — Frozen Contract

## Status

Approved direction. The goal is Claude Code's core experience: **one command in a
project directory starts interaction; interaction, scripting, resume, permissions,
configuration, and diagnostics share one CLI contract.** Priority is CLI-0 through
CLI-3 (contract freeze, entry layering, interactive mode, print mode). Desktop,
Service, and domain-specific commands are out of scope for the core CLI.

## Problem

`app.repl:main` is the only entry: CLI parsing, REPL, config, Wire, HTTP, and Setup
are entangled in one dispatch. `!`/`!!` run Host/Sandbox commands directly via
`create_subprocess_exec`, bypassing the permission and execution lifecycle.
`/resume` closes the old Runner. Interactive output and machine output have no
stable contract. CLI options, config files, and RunSnapshot are not fully aligned.

## Goals

1. One entry `app.cli:main` with layered `commands/`, `repl/`, `output/` modules.
2. Orthogonal dimensions: Task mode (ask|plan|run), Execution target (sandbox|local|ssh),
   Permission mode (prompt|auto-safe).
3. `-p` print mode with `text/json/stream-json` output and stable exit codes.
4. `-c`/`-r` reliable session resume; thread switching does not close background Runners.
5. `!` commands routed through the permission and execution lifecycle (no direct
   subprocess from the REPL).
6. Non-TTY: no ANSI, no animation, no interactive approval; fail explicitly when
   approval is required but unavailable.
7. Deprecation cycle for `--auto`/`--yolo`/`--max-turns` instead of sudden removal.
8. Project-scoped permission rules require Workspace Trust before first use.

## Non-goals (this pass, CLI-0..CLI-3)

- No full Harness Service; `client.py` AgentClient protocol is prepared but the CLI
  keeps working against the embedded Runner.
- No `electromind cp2k/lammps/deepmd/slurm` domain commands (they belong to
  Tools/Domain Runtime/Skills).
- No silent auto-update; update stays explicit (`electromind update`).
- No Workspace Trust UI (deferred with config scoping, CLI-5).

## Command surface

```text
electromind [PROMPT]           interactive mode
electromind -p [PROMPT]        non-interactive print mode

electromind session list|show ID|delete ID|export ID
electromind config get KEY|set KEY VALUE|unset KEY|edit|path|validate|sources
electromind skills list|show NAME|validate [NAME]
electromind doctor
electromind version
electromind completion bash|zsh|fish
electromind app [PATH]
electromind service start|status|stop|logs
```

## Flag contract

```text
-c, --continue                resume latest session of current project
-r, --resume [THREAD_ID]      resume session (no ID → interactive picker)
-p, --print                   non-interactive, exit when done

--mode ask|plan|run           task mode (default run)
--target sandbox|local|ssh    execution target (default sandbox)
--permission-mode prompt|auto-safe   (default prompt)

--project PATH
--add-dir PATH...
--model MODEL
--max-iterations N            (--max-turns kept as compat alias, deprecated)

--input-format text|stream-json
--output-format text|json|stream-json

--allowed-tools TOOL...
--disallowed-tools TOOL...

--no-session-persistence
--no-color
--quiet
--verbose
--debug
--log-file PATH

--config FILE                 (existing, extra config file)
--thread-id ID                (existing compat)
--blocking                    (existing, blocking REPL)
--wire / --http / --host / --port   (existing backend modes, kept for Desktop/plugin)
--backend                     (existing, sandbox backend override)
--execution-mode              (existing compat alias of --target)
--dev                         (existing, dev home)
--ssh-host / --ssh-config     (existing)
```

Rules:

- `ask`: read-only analysis. `plan`: read-only checks + plan generation. `run`:
  may request writes and execution.
- `auto-safe` only auto-approves operations the backend judges safe.
- Local target must be explicitly chosen and shows a risk warning.
- Sandbox or SSH resolution failure never falls back to Local.
- Deprecation: `--auto`/`--yolo` still work but print a deprecation warning;
  later releases remove `--yolo` and keep `--permission-mode auto-safe`.
- No `--dangerously-skip-permissions` in the first release.

## Exit codes

```text
0  success
2  CLI argument or configuration error
3  provider / auth error
4  permission denied
5  tool / execution failure
6  user cancel
7  service / protocol error
8  unknown or interrupted result
```

## stdout / stderr

```text
stdout → final result or structured events (parseable)
stderr → progress, warnings, diagnostics, debug logs
```

Non-TTY: no ANSI, no animation, no interactive approval; fail explicitly when
approval is required but no authorization rule exists.

## Interactive mode

```text
Enter        send
Shift+Enter  newline
Esc          cancel current response or tool
Ctrl+C       cancel current Run; clear input when idle
Ctrl+D       exit
Ctrl+R       input history search
/            command and Skill completion
@            project file path completion
!            run a command on the current execution target
```

- `!command` executes on the current target (sandbox by default), through
  `ExecutionManager → PermissionEngine → Execution Event → Result`. The implicit
  `!`=host / `!!`=sandbox semantics are removed.
- Status bar: `RUN · sandbox · prompt · deepseek-v4-pro · thread-123 · 42% context`.
- Run states: generating / running tool / awaiting approval / cancelling / completed.

## Slash commands

Built-in fixed logic: `/help /status /model /mode /target /permissions /config
/skills /sessions /resume /new /clear /compact /history /doctor /tasks /exit`.
Skills share the same `/` completion menu and load their body on demand.

## Print mode

```bash
electromind -p "总结当前项目" --output-format json
cat cp2k.out | electromind -p "分析这个输出"
```

- text: final human-readable result only.
- json: `{"status", "thread_id", "run_id", "result", "usage", "artifacts"}`.
- stream-json: one Protocol v2 event per line.
- stdin (piped) is prepended to the prompt; without a prompt, stdin is the prompt.
- Approval with a TTY: interactive prompt; without a TTY: fail with exit 4.

## Configuration scopes (CLI-5, structure reserved now)

```text
User    ~/.electromind/electromind.toml
Project <repo>/.electromind/electromind.toml
Local   <repo>/.electromind/electromind.local.toml
CLI     current invocation

precedence: CLI > Local > Project > User > built-in defaults
```

`electromind config sources` prints each effective key's origin. Project-shared
permission rules require Workspace Trust before first use.

## Implementation order

- CLI-0 contract freeze: this document, exit code constants, deprecation policy,
  regression tests locking old behavior.
- CLI-1 entry layering: `app.cli:main`, `commands/` package, Settings/RunOptions
  split, keep `electromind` startup compatible.
- CLI-2 interactive: bottom bar + steer preserved, unified keys, slash menu,
  `@` completion, status bar, `!` through permission lifecycle.
- CLI-3 print mode: `-p`, stdin, text/json/stream-json, exit codes, non-TTY rules.
- CLI-4 sessions: `-c`/`-r` against ThreadSessionManager; thread switch without
  closing the background Runner; cancel/approval bound to Run.
- CLI-5 config & diagnostics: `config *`, `doctor`, `version`, `completion`, `update`.
- CLI-6 distribution: wheel + uv/pipx, standalone binaries, installer, releases.

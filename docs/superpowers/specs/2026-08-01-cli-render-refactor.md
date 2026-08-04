# ElectroMind CLI Render Refactor

## Status

Approved direction. Renders the interactive CLI as a semantic task timeline with a
stable composer and a high-density status line, replacing ANSI-string concatenation
into a growing `body` string. Implemented: CLI-R1..R4 core, compact startup header,
`--inline` mode, `!` command routing through the permission lifecycle.

## Problem

`render.py` mixed ANSI, width math, banner, tool summaries, streaming text, and
status. `LayoutTerminal.body` was one growing string re-interpreted per frame.
Assistant/Tool/Approval/Error had no unified semantic model. The status line showed
only a run label. `full_screen=True` was fixed. Raw reasoning streamed as noise.
`!`/`!!` ran host/sandbox commands via `create_subprocess_exec`, bypassing the
permission lifecycle.

## Goals

1. Harness Event → `CliEventAdapter` → `EventReducer` → `CliViewModel` → `RenderItem[]`
   → TUI components → terminal backend. Backends send facts, reducer decides state,
   renderer only displays.
2. RenderItem union: User/Assistant/Activity/Tool/Approval/Error/RunStatus/Notice.
3. Colors only express semantics; every state carries a symbol:
   `✓ completed / ! warning / × failed / ● running / ? approval`.
4. Three output modes: full-screen TUI (default), `--inline` (preserve scrollback),
   non-TTY (no ANSI/spinner/approval; stdout = result or JSON only).
5. Composer always available: Enter sends, running Enter steers, Tab enqueues,
   Esc cancels, Ctrl+C cancel/clear/exit, Ctrl+R history, Ctrl+O copy reply,
   PageUp/PageDown scroll, `/` slash popup, `@` project file completion.
6. Approval card shows Tool/Target/Workdir/Risk; composer input is never mistaken
   for an approval answer.
7. Status line: `RUN · sandbox · prompt · deepseek-v4-pro · ~/water · ctx 31%`,
   hiding segments on narrow widths in priority order.
8. Startup shows a compact header, not the ASCII logo (`electromind --about` keeps
   the logo).
9. Tool cards show name, target, workdir, command, status, duration, exit code,
   output size — max 3–5 lines; full output opens in an overlay.
10. Raw reasoning is not shown by default; a public Activity item ("思考中…") is.

## Architecture

```text
src/app/tui/
├── theme.py        semantic color tokens + status symbols
├── view_model.py   RenderItem union, StatusLineState, ComposerState, CliViewModel
├── reducer.py      runner events → ordered items; text segments interleave tools
├── render.py       item → plain/ANSI lines (markdown-lite body)
├── store.py        structured items + per-(id, width-bucket) render cache
├── keymap.py       keyboard contract (Alt+Enter = newline; Shift+Enter needs
│                   terminal CSI-u which prompt_toolkit 3.0.52 does not parse)
├── completer.py    / command+Skill completion, @ project path completion
├── components.py   transcript pane / status line / composer / approval card
└── application.py  CliApp: state machine, event consumption, approval wait,
                    slash popup, overlays
```

The interactive entry lives in `app/concurrent_repl.py` (loop orchestration) and
`app/repl.py` (runner lifecycle, slash commands, `!` routing). The blocking REPL
keeps the classic line renderer; the TUI timeline renders semantically.

## Permission lifecycle for `!`

`!command` executes on the current Execution Target through
`runner.sandbox.commands.run` — the same path as the agent's `run_command` tool:
policy check (workdir confinement) → `mode_guard` (session-mode capability matrix)
→ audit record. The REPL never opens a subprocess directly. In `ask`/`plan` modes
dangerous commands are denied (exit 126) and shown as a failed Tool card.

## Deferred (CLI-R5/R6)

- Full overlay suite: session/file/model/target pickers, help panel (slash popup
  and approval card are in; pickers remain).
- Delta batching at 16–33 ms (store-level caching exists; per-frame assembly of
  the full timeline remains).
- Visible-range rendering for 5000+ items.
- Windows Terminal / tmux capability probes and resize stress beyond what
  prompt_toolkit already handles.
- `[tui] status_line` config; Workspace Trust; `service` command.

## Acceptance (this pass)

- [x] Startup header without ASCII logo (TUI); `--about` keeps the logo.
- [x] Composer usable while model/tool runs; Enter=steer, Tab=enqueue.
- [x] User / Assistant / Tool / Approval / Error are distinct semantic items.
- [x] Raw reasoning not shown by default.
- [x] Tool output folded; `[查看输出]` hint; full output overlay available.
- [x] Approval card shows Target / Workdir / Risk.
- [x] Status line shows mode, target, run status, permission, model, project, ctx%.
- [x] `!` cannot bypass the permission engine.
- [x] Full-screen / `--inline` / non-TTY behaviors separated.
- [x] Renderers consume the same CliViewModel; no runner creation in tui/.

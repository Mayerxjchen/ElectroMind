# pagentv4

语言：[中文](/zh/pagentv4/) | [English](/pagentv4/)

`pagentv4` is the newer typed API in this repository.

Use these pages if you want:

- `Provider` instead of `LLM`
- `Message` / `Messages` instead of `Session`
- `Runner` for thread-based orchestration, persistence, and sandbox workspaces
- A **sandbox** (companion computer) with file and command tools
- Optional **Thread** and **Skill** support for long-lived REPL-style apps

## Module layout

```text
core/       AgentCore, Message, Provider, Tool, Event
runtime/    loop_core, Runner, VanillaRunner, Thread
conversation/ ConversationStore implementations used through Thread
sandbox/    Backend, Sandbox, built-in file/command tools
adapters/   ACP encode/decode
skills/     SKILL.md discovery and on-demand loading
```

There are two layers inside `runtime/`:

- `loop_core` defines the shared run / turn / tool loop semantics
- `Runner` and `VanillaRunner` each add their own runtime environment around that shared loop

## Pages

- [Quick start](./quick-start)
- [Core types](./core-types)
- [Messages](./messages)
- [Tools](./tools)
- [Events](./events)
- [Sandbox](./sandbox)

## Status

New work should use `pagentv4` and `app` (terminal REPL). The top-level `pagent`
package still documents the older `Session + LLM` API for now.

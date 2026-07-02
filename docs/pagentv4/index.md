# pagentv4

语言：[中文](/zh/pagentv4/) | [English](/pagentv4/)

`pagentv4` is the newer typed API in this repository.

Use these pages if you want:

- `Provider` instead of `LLM`
- `Message` / `Messages` instead of `Session`
- `Runner` for orchestration, persistence, and sandbox sessions
- A **sandbox** (companion computer) with file and command tools
- Optional **Thread** and **Skill** support for long-lived REPL-style apps

## Module layout

```text
core/       Agent, Message, Provider, Tool, Event
runtime/    Runner, ConversationStore, Thread
sandbox/    Backend, Sandbox, built-in file/command tools
adapters/   ACP encode/decode
skills/     SKILL.md discovery and on-demand loading
```

## Pages

- [Quick start](./quick-start)
- [Core types](./core-types)
- [Messages](./messages)
- [Tools](./tools)
- [Events](./events)
- [Sandbox](./sandbox)

## Status

This documentation set is additive for now. The existing top-level `pagent`
docs still describe the stable `Session + LLM + arun_events()` API.

`pagentv2` remains in the repo for older examples and tests; new work should
start from `pagentv4`.

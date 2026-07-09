# pagentv4

语言：[中文](/zh/pagentv4/) | [English](/pagentv4/)

`pagentv4` 是本仓库中较新的类型化 API。

适合以下场景：

- 用 `Provider` 替代 `LLM`
- 用 `Message` / `Messages` 替代 `Session`
- 用 `Runner` 做基于 thread 的编排、持久化和 sandbox workspace
- 需要 **sandbox**（伴身电脑）提供文件与命令工具
- 需要 **Thread** 和 **Skill** 支撑长期 REPL 类应用

## 模块分层

```text
core/       AgentCore, Message, Provider, Tool, Event
runtime/    loop_core, Runner, VanillaRunner, Thread
conversation/ ConversationStore 实现，通过 Thread 使用
sandbox/    Backend, Sandbox, 内置文件/命令工具
adapters/   ACP 编解码
skills/     SKILL.md 发现与按需加载
```

`runtime/` 里有两层：

- `loop_core` 统一 run / turn / tool 的事件循环语义
- `Runner` 与 `VanillaRunner` 在这套共享循环外包上各自的运行环境

## 文档目录

- [快速开始](./quick-start)
- [核心类型](./core-types)
- [消息](./messages)
- [工具](./tools)
- [事件](./events)
- [Sandbox](./sandbox)

## 状态说明

新工作请使用 `pagentv4` 与 `app`（终端 REPL）。顶层 `pagent` 包仍保留较旧的
`Session + LLM` API 文档。

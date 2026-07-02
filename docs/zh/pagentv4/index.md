# pagentv4

语言：[中文](/zh/pagentv4/) | [English](/pagentv4/)

`pagentv4` 是本仓库中较新的类型化 API。

适合以下场景：

- 用 `Provider` 替代 `LLM`
- 用 `Message` / `Messages` 替代 `Session`
- 用 `Runner` 做编排、持久化和 sandbox 会话
- 需要 **sandbox**（伴身电脑）提供文件与命令工具
- 需要 **Thread** 和 **Skill** 支撑长期 REPL 类应用

## 模块分层

```text
core/       Agent, Message, Provider, Tool, Event
runtime/    Runner, ConversationStore, Thread
sandbox/    Backend, Sandbox, 内置文件/命令工具
adapters/   ACP 编解码
skills/     SKILL.md 发现与按需加载
```

## 文档目录

- [快速开始](./quick-start)
- [核心类型](./core-types)
- [消息](./messages)
- [工具](./tools)
- [事件](./events)
- [Sandbox](./sandbox)

## 状态说明

这套文档目前是增量补充。顶层 `pagent` 文档仍描述稳定的
`Session + LLM + arun_events()` API。

仓库里仍保留 `pagentv2` 供旧示例和测试使用；新工作请从 `pagentv4` 开始。

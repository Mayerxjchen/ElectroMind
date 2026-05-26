# 核心概念

语言：四川话 | [English](/guide/concepts) | [普通话](/zh/guide/concepts) | [日本語](/ja/guide/concepts)

跟 `LLM`、`Agent` 拼起的三块：

```mermaid
flowchart LR
  P[提示词<br/>Session]
  T[Tools]
  M[Memory 可选]
  A[Agent]
  L[LLM]

  P --> A
  T --> A
  M -.-> P
  A <--> L
```

| 主题 | 文档 |
|------|------|
| messages、系统提示、对话历史 | [提示词](./prompt) |
| `@tool` 跟工具循环 | [工具](./tools) |
| 可选备注，手动注入 | [记忆](./memory) |

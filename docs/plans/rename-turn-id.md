# 重命名 `turn_id` → `run_id`（或 `round_id`）

> 状态：TODO（设计债，尚未实现）
> 记录：2026-07

## 问题

pagentv4 里 **「turn」一词被用了两次**，容易和 loop 内的 `turn`（`TurnBegin` / `TurnEnd`）混淆：

| 符号 | 实际含义 |
|------|----------|
| loop `turn`（0, 1, 2…） | 一次 `runner.run()` **内部**的 LLM 调用序号 |
| `Message.turn_id` | **第几条 user 消息**；一次 `runner.run()` 内所有消息共享同一 id |

`turn_id` 在语义上更接近 **一次 run**（`runner.run(user_input)`），而不是 loop turn。

赋值见 `src/pagentv4/runtime/loop_adapter.py`：`turn_id = messages.max_turn_id() + 1`，随每次 `run()` 递增。

## 建议方向

优先考虑 **`run_id`**（与 `RunBegin` / `RunEnd` 对齐），或 **`round_id`**（强调用户对话轮次）。

- `system` 消息可继续用 `run_id=0`（或保留特例）。
- loop 内序号继续叫 **`turn`**，不改。

## 影响面（改名时需扫）

- `Message.turn_id`、`Messages.max_turn_id()`
- `RunState.turn_id`
- `append_message` / `loop_adapter.run`
- JSONL / SQLite conversation 持久化字段
- `trace/view.py` 分组与 UI 标签
- `docs/pagentv4/core-types.md` 术语表
- 测试与 examples

## 迁移策略（待定）

1. 新增字段 + 读写双兼容一段时间；或
2. 一次性 breaking rename + JSONL 迁移脚本。

## 非目标

- 不把 `run_id` 做成全局 UUID（保持 thread 内递增整数即可）。
- 不改动 loop `turn` / `TurnResult` / `TurnEnd` 命名。

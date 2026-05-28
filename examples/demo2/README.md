# demo2 — LiveAgent CLI

Duplex-bus interactive demo: `readfile`, `bash` (ls), and **`ask_user`**.

```bash
export DEEPSEEK_API_KEY="your-key"
uv run examples/demo2/cli.py
```

## How it works

- **Agent** runs `arun_events` in the background and pushes every outbound event to `agent.bus` (`owire`).
- **CLI** consumes `bus.get_owire()` / `wait_owire()`, renders streaming text, and on `HumanInputRequired` prompts stdin, then replies with `push_iwire(agent.bus, HumanReply(...))`.
- **`ask_user`** blocks the tool until the human answers; the run continues only after `HumanReply` arrives.

Same slash commands as `examples/cli_events.py` (`/help`, `/reset`, `/context`, …).

---

## Walkthrough: 猜人游戏（`ask_user` 人机协作）

下面是一次真实会话的玩法说明。你对 Agent 说一句话设定任务，之后**模型只通过 `ask_user` 向你提问**，根据你的回答缩小范围，直到猜出你心里想的人。

### 启动任务

在 `You>` 输入：

```text
我设想一个任务，你使用ask_user来问我问题，我回答帮助你缩小范围，知道你猜出。
```

CLI 会流式显示 `reasoning:`，并在模型调用 `ask_user` 时出现黄色问题与绿色 `>` 提示；你的回答会显示为 `✓ …`。

### 第一轮：猜「秦始皇」

| 步骤 | 模型问（`ask_user`） | 你答 |
|------|----------------------|------|
| 1 | 物体 / 概念 / **人** / 地点？ | 人 |
| 2 | **真实**还是虚构？ | 现实 |
| 3 | 在世还是**去世**？ | 不在了 |
| 4 | **中国人**还是外国人？ | 中 |
| 5 | 领域（科学、文学、**历史**…）？ | 历史 |
| 6 | 历史学家还是**帝王/将领**？ | 帝王 |
| 7 | **哪个朝代**？ | 先秦 |
| 8 | 夏商周春秋**战国**哪段？ | 战国后期 |
| 9 | 哪个诸侯国君主？ | 不是，他完成了伟大的 |

模型结合「战国后期」「统一」等线索，在正文中猜出：**秦始皇（嬴政）**。

### 第二轮：再说「再来一次」

```text
You> 再来一次
```

新一局从「物体 / 人 / 地点 / 概念」重新开始。示例回答路径（会话节选）：

| 步骤 | 问题要点 | 你答 |
|------|----------|------|
| 1 | 类别 | 人物 |
| 2 | 真实 / 虚构 | 真实 |
| 3 | 在世 / 去世 | 还在 |
| 4 | 中 / 外 | 中国 |
| 5 | 男 / 女 | 女 |
| 6 | 领域 | 演艺圈 |
| 7 | 演员 / 歌手 / 主持人 | 演员 |
| 8 | 大陆 / 港澳台 | 大陆 |

之后模型会继续用 `ask_user` 追问年代、代表作等，直到猜出具体人物（会话中可能在长 `reasoning` 流式阶段停顿较久，属模型/API 等待，可观察终端中的 `…` 心跳）。

### 设计要点（为什么适合 demo2）

1. **必须用 `ask_user`**：缺信息时不能瞎猜，要问人——正好演示 `HumanInputRequired` → stdin → `HumanReply`。
2. **多轮、窄化搜索**：一局里连续十几次 tool 调用，能压测 duplex bus 与 CLI 消费是否稳定。
3. **答案简短**：是/否、朝代、领域等，适合终端交互。

### 常见问题

- **只看到 `→ ask_user(...)` 没有黄色问题**：旧版 CLI 用同步 `input()` 会卡住事件循环；当前 demo2 已改为 `asyncio.to_thread(input)` + bus `wait_owire`。
- **`reasoning:` 后长时间无输出**：多为 API 流式未返回下一 token，稍等或 `Ctrl+C` 中断。
- **模型在 reasoning 里「自问自答」**：偶发会把问题打在 `reasoning:` 行里；仍以黄色 `ask_user` 提示为准。

### 相关代码

| 文件 | 作用 |
|------|------|
| `examples/demo2/cli.py` | 消费 `owire`、处理 `HumanInputRequired` |
| `src/pagent_live/tools.py` | `ask_user` 工具 |
| `src/pagent_live/context.py` | `request_human` / `wait_reply` |
| `src/pagent_live/spec.md` | Bus 与 Event 约定 |

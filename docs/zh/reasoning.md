# reasoning_content 示例

语言：中文 | [English](/reasoning) | [日本語](/ja/reasoning) | [四川话](/sc/reasoning)

DeepSeek 等模型可在响应中返回 **`reasoning_content`**（思考过程）和 **`content`**（面向用户的答案）。pagent 通过 **`RunEnd`** 承载这两部分，流式场景下通过 **`ReasoningDelta`** / **`TextDelta`** 事件分别推送。

详见事件说明：[事件流](./events)

## 用法

下面展示直接 API 写法。可运行示例统一放在
[`examples/README.md`](https://github.com/SyncLionPaw/pagent/blob/main/examples/README.md)。

## 非流式：读取 RunEnd

```python
end = await agent.run(question, reasoning_effort="medium")

print(end.reasoning_content)  # 思考过程（可能为空，视模型而定）
print(end.content)            # 最终答案

# session 里 assistant 消息也会带上 reasoning_content
assert agent.session.messages[-1].get("reasoning_content") == end.reasoning_content
```

注意：请打印 **`end.content`**，不要 `print(end)`，否则会看到整段 `RunEnd(...)` repr。

## 流式：arun_events

```python
answer_started = False
async for event in agent.arun_events(question, reasoning_effort="medium"):
    match event:
        case ReasoningDelta(text=t):
            print(t, end="", flush=True)   # 推理流
        case TextDelta(text=t):
            if not answer_started:
                print("\nanswer: ", end="", flush=True)
                answer_started = True
            print(t, end="", flush=True)       # 正文流
        case RunEnd():
            print()
```

`agent.arun()` 仍只产出正文字符串（内部过滤 `TextDelta`），与 CLI 行为一致。

## 题目说明

**英文（默认）** — 三盒标签逻辑题，鼓励分步推理。

**中文（`--zh`）** — 鸡兔同笼：35 个头、94 只脚，求鸡兔各几只（标准解：鸡 23，兔 12）。

可在 `reasoning_common.py` 中修改 `QUESTION_EN` / `QUESTION_ZH`。

## reasoning_effort

与 CLI 的 `/effort` 相同，通过 `run_kwargs` 传给模型，例如：

```python
await agent.run("...", reasoning_effort="medium")
await agent.arun_events("...", reasoning_effort=0.5)
```

是否返回 `reasoning_content` 取决于 **Provider 与模型**，pagent 只负责透传与写入 `session`。

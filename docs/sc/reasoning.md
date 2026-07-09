# reasoning_content 例子

语言：四川话 | [English](/reasoning) | [普通话](/zh/reasoning) | [日本語](/ja/reasoning)

DeepSeek 这类模型可以返回 **`reasoning_content`**（脑壳里头啷个想的）跟 **`content`**（摆给用户看的答案）。pagent 用 **`RunEnd`** 装这两坨，流式用 **`ReasoningDelta`** / **`TextDelta`** 分开推，看得清清楚楚。

详见：[事件流](./events)

## 用法

下面展示直接 API 写法。能跑的示例统一放在
[`examples/README.md`](https://github.com/SyncLionPaw/pagent/blob/main/examples/README.md)。

`--zh` 用中文 system prompt 跟鸡兔同笼题；默认英文逻辑题（三盒标签）。

## 非流式：读 RunEnd

```python
end = await agent.run(question, reasoning_effort="medium")

print(end.reasoning_content)
print(end.content)

assert agent.session.messages[-1].get("reasoning_content") == end.reasoning_content
```

注意：打 **`end.content`**，莫 `print(end)`，哦豁，整坨 `RunEnd(...)` repr 冒出来，打脑壳。

## 流式：arun_events

```python
answer_started = False
async for event in agent.arun_events(question, reasoning_effort="medium"):
    match event:
        case ReasoningDelta(text=t):
            print(t, end="", flush=True)
        case TextDelta(text=t):
            if not answer_started:
                print("\nanswer: ", end="", flush=True)
                answer_started = True
            print(t, end="", flush=True)
        case RunEnd():
            print()
```

`agent.arun()` 还是只吐正文字符串，跟 CLI 一样，撇脱。

## 题目说明

**英文（默认）** — 三盒标签逻辑题，慢慢摆。

**中文（`--zh`）** — 鸡兔同笼：35 个头、94 只脚（标准解：鸡 23，兔 12）。

改题在 `reasoning_common.py` 里动 `QUESTION_EN` / `QUESTION_ZH`。

## reasoning_effort

跟 CLI 的 `/effort` 一样，经 `run_kwargs` 传给模型：

```python
await agent.run("...", reasoning_effort="medium")
await agent.arun_events("...", reasoning_effort=0.5)
```

返不返 `reasoning_content` 看 **Provider 跟模型**，pagent 只负责透传跟写 `session`，这个莫得办法。你那边 UI 把脑壳转区 **巴倒** 正文旁边摆，用户就看得安逸 — 差两个字段？**不存在**，Event 里都有。

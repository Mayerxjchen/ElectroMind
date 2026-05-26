# reasoning_content 例子

语言：四川话 | [English](/reasoning) | [普通话](/zh/reasoning) | [日本語](/ja/reasoning)

DeepSeek 这类模型可以返回 **`reasoning_content`**（脑壳里咋个想的）跟 **`content`**（给用户看的答案）。pagent 用 **`RunEnd`** 装这两坨，流式用 **`ReasoningDelta`** / **`TextDelta`** 分开推。

详见：[事件流](./events)

## 示例脚本

| 文件 | 模式 | 说明 |
|------|------|------|
| [reasoning_run.py](https://github.com/SyncLionPaw/pagent/blob/main/examples/reasoning_run.py) | 非流式 | `agent.run()` → `RunEnd` |
| [reasoning_stream.py](https://github.com/SyncLionPaw/pagent/blob/main/examples/reasoning_stream.py) | 流式 | `agent.arun_events()` → `ReasoningDelta` + `TextDelta` |
| [reasoning_common.py](https://github.com/SyncLionPaw/pagent/blob/main/examples/reasoning_common.py) | 共用 | 题目、`make_agent()` |

还有：[simple_qa.py](https://github.com/SyncLionPaw/pagent/blob/main/examples/simple_qa.py)、[cli.py](https://github.com/SyncLionPaw/pagent/blob/main/examples/cli.py)。

## 运行

```bash
export DEEPSEEK_API_KEY="your-key-here"

uv run examples/reasoning_run.py
uv run examples/reasoning_stream.py

uv run examples/reasoning_run.py --zh
uv run examples/reasoning_stream.py --zh
```

`--zh` 用中文 system prompt 跟鸡兔同笼题；默认英文逻辑题（三盒标签）。

## 非流式：读 RunEnd

```python
end = await agent.run(question, reasoning_effort="medium")

print(end.reasoning_content)
print(end.content)

assert agent.session.messages[-1].get("reasoning_content") == end.reasoning_content
```

注意：打 **`end.content`**，莫 `print(end)`，不然整坨 `RunEnd(...)` repr 冒出来。

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

`agent.arun()` 还是只吐正文字符串，跟 CLI 一样。

## 题目说明

**英文（默认）** — 三盒标签逻辑题。

**中文（`--zh`）** — 鸡兔同笼：35 个头、94 只脚（标准解：鸡 23，兔 12）。

改题在 `reasoning_common.py` 里动 `QUESTION_EN` / `QUESTION_ZH`。

## reasoning_effort

跟 CLI 的 `/effort` 一样，经 `run_kwargs` 传给模型：

```python
await agent.run("...", reasoning_effort="medium")
await agent.arun_events("...", reasoning_effort=0.5)
```

返不返 `reasoning_content` 看 **Provider 跟模型**，pagent 只负责透传跟写 `session`。

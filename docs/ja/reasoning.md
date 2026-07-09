# reasoning_content の例

言語: 日本語 | [English](/reasoning) | [简体中文](/zh/reasoning) | [四川话](/sc/reasoning)

DeepSeek などは **`reasoning_content`**（思考過程）と **`content`**（ユーザー向け回答）を返すことがあります。pagent は両方を **`RunEnd`** に載せ、ストリームでは **`ReasoningDelta`** と **`TextDelta`** で分けます。

イベント一覧: [イベント](./events)

## 使い方

以下は直接 API の形です。実行可能なサンプルは
[`examples/README.md`](https://github.com/SyncLionPaw/pagent/blob/main/examples/README.md)
に分類されています。

## 非ストリーム: RunEnd

```python
end = await agent.run(question, reasoning_effort="medium")
print(end.reasoning_content)
print(end.content)
```

## ストリーム: arun_events

```python
async for event in agent.arun_events(question, reasoning_effort="medium"):
    match event:
        case ReasoningDelta(text=t):
            print(t, end="", flush=True)
        case TextDelta(text=t):
            print(t, end="", flush=True)
        case RunEnd():
            print()
```

`arun()` は回答テキスト（`TextDelta`）のみです。

## reasoning_effort

`run_kwargs` に渡します（例: `reasoning_effort="medium"`）。`reasoning_content` が出るかはプロバイダとモデル次第です。

# reasoning_content の例

言語: 日本語 | [English](/reasoning) | [简体中文](/zh/reasoning) | [四川话](/sc/reasoning)

DeepSeek などは **`reasoning_content`**（思考過程）と **`content`**（ユーザー向け回答）を返すことがあります。pagent は両方を **`RunEnd`** に載せ、ストリームでは **`ReasoningDelta`** と **`TextDelta`** で分けます。

イベント一覧: [イベント](./events)

## サンプルスクリプト

| ファイル | モード | 説明 |
|----------|--------|------|
| [reasoning_run.py](https://github.com/SyncLionPaw/pagent/blob/main/examples/reasoning_run.py) | 非ストリーム | `agent.run()` → `RunEnd` |
| [reasoning_stream.py](https://github.com/SyncLionPaw/pagent/blob/main/examples/reasoning_stream.py) | ストリーム | `arun_events()` → `ReasoningDelta` + `TextDelta` |
| [reasoning_common.py](https://github.com/SyncLionPaw/pagent/blob/main/examples/reasoning_common.py) | 共通 | 問題文、`make_agent()` |

ほか [simple_qa.py](https://github.com/SyncLionPaw/pagent/blob/main/examples/simple_qa.py)、[cli.py](https://github.com/SyncLionPaw/pagent/blob/main/examples/cli.py)。

## 実行

```bash
export DEEPSEEK_API_KEY="your-key"

uv run examples/reasoning_run.py
uv run examples/reasoning_stream.py

uv run examples/reasoning_stream.py --zh   # 中国語プロンプト（鶏ウサギ問題）
```

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

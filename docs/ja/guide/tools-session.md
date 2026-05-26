# ツールとセッション

言語: 日本語 | [English](/guide/tools-session) | [简体中文](/zh/guide/tools-session) | [四川话](/sc/guide/tools-session)

## Session

`Session(system_prompt)` は **OpenAI チャット形式** のメッセージリストを保持します。

```python
session += {"role": "user", "content": "Hello"}
```

| クラス | 用途 |
|--------|------|
| `Session` | 基本バッファ |
| `SlidingWindowSession` | **トークン**上限でトリム（メッセージ数ではない） |
| `CompactingSession` | コンテキストが大きいとき LLM で要約圧縮 |

## ツール

`@tool()` で関数を装飾 — 型ヒントと docstring からスキーマを生成:

```python
from pagent import tool

@tool()
def calculate(expression: str) -> str:
    """Evaluate a math expression."""
    ...
```

`Agent(..., tools=[calculate])` に渡します。モデルは OpenAI 形式の `tools` を受け取り、pagent が実行して `role: tool` を session に追加します。

組み込み（任意）: `web_search`, `clock`, `region` — [defaults.py](https://github.com/SyncLionPaw/pagent/blob/main/src/pagent/defaults.py)

## Agent ループ

```python
Agent(llm, session, tools=[], max_turns=8)
```

各ターン: モデル → 必要ならツール → 再びモデル。ツールがなくなるか `max_turns` まで。ストリームは `arun_events()` / `arun_wire()`。

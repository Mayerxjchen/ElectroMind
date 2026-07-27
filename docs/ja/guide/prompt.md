# プロンプト

言語: [日本語](/ja/guide/prompt) | [English](/guide/prompt) | [简体中文](/zh/guide/prompt) | [四川话](/sc/guide/prompt)

`Session` でシステムプロンプトと履歴を持ち、`Agent` に渡します。

## システムプロンプト

```python
from pagent import Session

session = Session("簡潔な助手として答えてください。")
```

## ユーザーメッセージ

```python
session += {"role": "user", "content": "2+2 は？"}
```

## 実行

```python
from pagent import Agent, LLM

agent = Agent(llm=LLM("gpt-4o-mini"), session=session, tools=[], max_turns=24)
await agent.run("2+2 は？")
```

`run()` のたびに user と返答が `session` に追加されます。

## 会話が長いとき

トークンが多すぎる場合は `SlidingWindowSession` で古いターンを削除するか、`CompactingSession` で `await session.compact()` 要約します。

```python
from pagent import SlidingWindowSession, CompactingSession, LLM

session = SlidingWindowSession("助手として答えて。", max_tokens=8000)

llm = LLM("gpt-4o-mini")
session = CompactingSession("助手として答えて。", llm=llm, compact_at_tokens=6000)
if session.should_compact:
    await session.compact()
```

## 保存

```python
session.save_to_file("chat.json")
```

## 関連

- [ツール](./tools) · [メモリ](./memory) · [クイックスタート](./quick-start)

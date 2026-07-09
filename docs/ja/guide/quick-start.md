# クイックスタート

言語: 日本語 | [English](/guide/quick-start) | [简体中文](/zh/guide/quick-start) | [四川话](/sc/guide/quick-start)

前提: [インストール](./install)（Python 3.11+、pip / uv / conda）。

## 最小の Agent

```python
import asyncio
import os

from pagent import Agent, LLM, Session, tool


@tool()
def get_weather(city: str) -> str:
    """Return weather for the city."""
    return f"Sunny in {city} today."


async def main():
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY を設定してください。")

    agent = Agent(
        llm=LLM("gpt-4o-mini"),
        session=Session("You are helpful. Use tools when needed."),
        tools=[get_weather],
        max_turns=8,
    )

    result = await agent.run("What's the weather in Xiamen?")
    print(result.content)


asyncio.run(main())
```

`run()` は **`RunEnd`** を返します。回答は `.content` を使います。

## ストリーミング API

| API | 戻り値 | 用途 |
|-----|--------|------|
| `agent.run()` | `RunEnd` | ストリーム不要 |
| `agent.arun()` | `str` チャンク | テキストのみのタイプ表示 |
| `agent.arun_events()` | `Event` オブジェクト | Python UI、テスト |
| `agent.arun_wire()` | NDJSON 行 | ブラウザ、VS Code 拡張など |

次へ: [プロバイダと API Key](./providers) · [イベント](../events) · [Wire プロトコル](../wire)

## サンプル（リポジトリの clone が必要）

```bash
git clone https://github.com/SyncLionPaw/pagent.git
cd pagent
export DEEPSEEK_API_KEY="your-key"

uv run pagent
uv run python -m examples.pagentv4.thread_based.conversation_only
uv run python -m examples.pagentv4.thread_based.code_runner
uv run --with fastapi --with uvicorn python examples/wire_browser/server.py
```

| サンプル | 説明 |
|----------|------|
| [`examples/README.md`](https://github.com/SyncLionPaw/pagent/blob/main/examples/README.md) | 分類済みサンプル索引 |
| [`examples/pagentv4/thread_based`](https://github.com/SyncLionPaw/pagent/tree/main/examples/pagentv4/thread_based) | ChatRunner / CodeRunner examples |
| [`examples/pagentv4/runner`](https://github.com/SyncLionPaw/pagent/tree/main/examples/pagentv4/runner) | Runner.create examples |
| [wire_browser](https://github.com/SyncLionPaw/pagent/tree/main/examples/wire_browser) | FastAPI + ブラウザ UI |

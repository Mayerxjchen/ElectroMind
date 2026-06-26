"""pagentv3 demo — JSONL persistence with conversation_id.

Usage:
    uv run python -m examples.pagentv3_persistence_demo

Requires:
    ollama serve
    ollama pull gemma4

This example shows:
1. create a new conversation automatically
2. run one turn and persist Messages to JSONL
3. recreate Agent from the same conversation_id
4. continue the conversation from persisted history
"""

import asyncio
from pathlib import Path

from pagentv3 import Agent, JsonlBackend, Ollama, Persistence, TextDelta


async def show_reply(agent: Agent, user_input: str) -> None:
    print(f"\nYou: {user_input}")
    parts: list[str] = []
    async for event in agent.arun(user_input):
        if isinstance(event, TextDelta):
            parts.append(event.text)
    print(f"Assistant: {''.join(parts)}")


async def main() -> None:
    store_dir = Path("data/pagentv3_demo")
    persistence = Persistence(JsonlBackend(store_dir))

    agent = Agent(
        Ollama("gemma4"),
        persistence=persistence,
        system="每次只说一句话，高冷。",
    )

    print(f"Store dir: {store_dir.resolve()}")
    print(f"conversation_id: {agent.conversation_id}")

    await show_reply(agent, "My name is Alice. Remember it for this conversation.")

    print("\nPersisted messages after turn 1:")
    print(agent.messages)

    restored_agent = Agent(
        Ollama("gemma4"),
        persistence=persistence,
        conversation_id=agent.conversation_id,
    )

    print("\nReloaded messages from JSONL:")
    print(restored_agent.messages)

    await show_reply(restored_agent, "What is my name?")

    print("\nPersisted messages after turn 2:")
    print(restored_agent.messages)


if __name__ == "__main__":
    asyncio.run(main())

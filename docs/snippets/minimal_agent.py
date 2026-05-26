import asyncio
import os

from pagent import LLM, Agent, Session, tool


@tool()
def get_weather(city: str) -> str:
    """Return weather for the city."""
    return f"Sunny in {city} today."


async def main():
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("Set OPENAI_API_KEY first.")

    agent = Agent(
        llm=LLM("gpt-4o-mini"),
        session=Session("You are helpful. Use tools when needed."),
        tools=[get_weather],
        max_turns=8,
    )

    result = await agent.run("What's the weather in Xiamen?")
    print(result.content)


asyncio.run(main())

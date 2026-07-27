import asyncio
import os

from pagent import LLM, Agent, Session, tool


@tool()
def get_weather(city: str) -> str:
    """Return weather for the city."""
    return f"Sunny in {city} today."


async def main():
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise SystemExit("Set ANTHROPIC_API_KEY first.")

    agent = Agent(
        llm=LLM(
            "claude-sonnet-4-20250514",
            base_url="https://api.anthropic.com/v1",
            apikey=os.getenv("ANTHROPIC_API_KEY"),
        ),
        session=Session("You are helpful. Use tools when needed."),
        tools=[get_weather],
        max_turns=24,
    )

    result = await agent.run("What's the weather in Xiamen?")
    print(result.content)


asyncio.run(main())

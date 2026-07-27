import asyncio
import os

from pagent import LLM, Agent, Session, tool


@tool()
def get_weather(city: str) -> str:
    """Return weather for the city."""
    return f"Sunny in {city} today."


async def main():
    if not os.getenv("MOONSHOT_API_KEY"):
        raise SystemExit("Set MOONSHOT_API_KEY first.")

    agent = Agent(
        llm=LLM(
            "kimi-k2.5",
            base_url="https://api.moonshot.cn/v1",
            apikey=os.getenv("MOONSHOT_API_KEY"),
        ),
        session=Session("You are helpful. Use tools when needed."),
        tools=[get_weather],
        max_turns=24,
    )

    result = await agent.run("What's the weather in Xiamen?")
    print(result.content)


asyncio.run(main())

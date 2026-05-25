"""A simple agent that can answer questions and use tools.

Usage:
    export DEEPSEEK_API_KEY="your-key-here"
    python -m examples.simple_qa
"""

import asyncio
import os

from pagent import Agent, DeepSeek, Session, tool


@tool()
def get_weather(city: str) -> str:
    """Get the current weather for a city.

    Args:
        city: The city name, e.g. "Beijing", "Shanghai".
    """
    # In production, call a real weather API here.
    weathers = {
        "Beijing": "Sunny, 28°C",
        "Shanghai": "Cloudy, 25°C",
        "Shenzhen": "Rainy, 30°C",
    }
    return weathers.get(city, f"Weather data not available for {city}")


@tool()
def calculate(expression: str) -> str:
    """Evaluate a math expression and return the result.

    Args:
        expression: A Python math expression, e.g. "2 + 3 * 4".
    """
    try:
        result = eval(expression, {"__builtins__": {}}, {})
        return str(result)
    except Exception as e:
        return f"Error: {e}"


async def main():
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("Please set DEEPSEEK_API_KEY: export DEEPSEEK_API_KEY='your-key'")

    session = Session("You are a helpful assistant. Answer questions concisely.")
    llm = DeepSeek("deepseek-v4-flash")
    agent = Agent(llm=llm, session=session, tools=[get_weather, calculate])

    # Simple Q&A without tools
    reply = await agent.run("What is the capital of France?")
    print(f"Q: What is the capital of France?")
    print(f"A: {reply}\n")

    # Q&A with tool use
    reply = await agent.run("How's the weather in Beijing?")
    print(f"Q: How's the weather in Beijing?")
    print(f"A: {reply}\n")

    # Math calculation via tool
    reply = await agent.run("What is 123 * 456?")
    print(f"Q: What is 123 * 456?")
    print(f"A: {reply}")


if __name__ == "__main__":
    asyncio.run(main())

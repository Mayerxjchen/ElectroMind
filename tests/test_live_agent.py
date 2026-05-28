import asyncio
from dataclasses import dataclass
from types import SimpleNamespace

from pagent import Session, tool
from pagent_live import (
    DuplexBus,
    HumanInputRequired,
    LiveAgent,
    ask_user,
    push_iwire,
    wait_reply,
)
from pagent_live.live_events import HumanReply


class FakeStreamLLM:
    def __init__(self, turns):
        self._turns = [list(chunks) for chunks in turns]
        self.invoke_stream_calls = []

    async def invoke_stream(self, messages, tools=None, **run_kwargs):
        self.invoke_stream_calls.append((list(messages), tools, run_kwargs))
        for chunk in self._turns.pop(0):
            yield chunk


def make_chunk(content=None, tool_calls=None, usage=None, reasoning_content=None):
    delta = SimpleNamespace(
        content=content, tool_calls=tool_calls, reasoning_content=reasoning_content
    )
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=usage)


@dataclass(frozen=True)
class Ping:
    message: str


def test_duplex_bus_push_get():
    bus = DuplexBus()
    bus.push_owire(Ping("a"))
    assert bus.get_owire() == Ping("a")
    assert bus.get_owire() is None


def test_wait_reply():
    async def main():
        bus = DuplexBus()

        async def waiter():
            text = await wait_reply("tc1")
            assert text == "hello"

        task = asyncio.create_task(waiter())
        await asyncio.sleep(0)
        push_iwire(bus, HumanReply("tc1", "hello"))
        await task

    asyncio.run(main())


def test_live_agent_bus_on_construct():
    agent = LiveAgent(FakeStreamLLM([[make_chunk(content="hi")]]), Session(""))
    assert agent.bus is not None


@tool()
def ping(context, msg: str) -> str:
    context.emit(Ping(msg))
    return f"echo:{msg}"


def test_live_agent_emit_from_tool():
    tc = type(
        "TC",
        (),
        {
            "index": 0,
            "id": "c1",
            "type": "function",
            "function": type(
                "FN",
                (),
                {"name": "ping", "arguments": '{"msg":"x"}'},
            )(),
        },
    )()
    llm = FakeStreamLLM(
        [
            [make_chunk(tool_calls=[tc])],
            [make_chunk(content="done")],
        ]
    )
    agent = LiveAgent(llm, Session(""), tools=[ping], max_turns=4)
    kinds = []
    pings = []

    async def collect():
        async def drive():
            async for _ in agent.arun_events("go"):
                pass

        run_task = asyncio.create_task(drive())
        while not run_task.done():
            event = agent.bus.get_owire()
            if event is not None:
                kinds.append(type(event).__name__)
                if isinstance(event, Ping):
                    pings.append(event.message)
            await asyncio.sleep(0)
        while (event := agent.bus.get_owire()) is not None:
            kinds.append(type(event).__name__)
            if isinstance(event, Ping):
                pings.append(event.message)
        await run_task

    asyncio.run(collect())
    assert (
        kinds.index("ToolCallBegin") < kinds.index("Ping") < kinds.index("ToolResult")
    )
    assert pings == ["x"]
    assert kinds[-1] == "RunEnd"


def test_live_agent_ask_user():
    tc = type(
        "TC",
        (),
        {
            "index": 0,
            "id": "c1",
            "type": "function",
            "function": type(
                "FN",
                (),
                {"name": "ask_user", "arguments": '{"question":"City?"}'},
            )(),
        },
    )()
    llm = FakeStreamLLM(
        [
            [make_chunk(tool_calls=[tc])],
            [make_chunk(content="Xiamen.")],
        ]
    )
    agent = LiveAgent(llm, Session("helpful"), tools=[ask_user], max_turns=4)
    kinds = []

    async def collect():
        async def drive():
            async for _ in agent.arun_events("Book travel"):
                pass

        run_task = asyncio.create_task(drive())
        while not run_task.done():
            event = agent.bus.get_owire()
            if event is not None:
                kinds.append(type(event).__name__)
                if isinstance(event, HumanInputRequired):
                    push_iwire(agent.bus, HumanReply(event.tool_call_id, "Xiamen"))
            await asyncio.sleep(0)
        while (event := agent.bus.get_owire()) is not None:
            kinds.append(type(event).__name__)
            if isinstance(event, HumanInputRequired):
                push_iwire(agent.bus, HumanReply(event.tool_call_id, "Xiamen"))
        await run_task

    asyncio.run(collect())
    assert "HumanInputRequired" in kinds
    assert kinds.index("HumanInputRequired") < kinds.index("ToolResult")
    tool_msgs = [m for m in agent.session.messages if m["role"] == "tool"]
    assert tool_msgs[-1]["content"] == "Xiamen"

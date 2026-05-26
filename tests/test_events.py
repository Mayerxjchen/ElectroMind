from pagent import (
    Event,
    RunBegin,
    RunEnd,
    StepEnd,
    TextDelta,
    ToolCallBegin,
    ToolResult,
    TurnBegin,
    TurnEnd,
)


def test_event_union_is_dataclass_instance():
    events: list[Event] = [
        RunBegin("hi"),
        TurnBegin(0),
        TextDelta("a"),
        StepEnd("", [], "", None),
        ToolCallBegin("c1", "echo", "{}"),
        ToolResult("c1", "echo", "ok"),
        TurnEnd(0, stopped=True),
        RunEnd(content="done"),
    ]
    assert len(events) == 8


def test_events_are_frozen():
    e = TextDelta("x")
    try:
        e.text = "y"  # type: ignore[misc]
        raised = False
    except AttributeError:
        raised = True
    assert raised

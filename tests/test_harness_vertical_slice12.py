"""Section XI step 12: artifact export with content verification.

The agent delivers a file via copy_to_host; the artifact must land in the
host's artifacts directory with byte-identical content, and the FileChange
event emitted for the delivery carries thread/run identity.
"""

from __future__ import annotations

import json

import pytest

from electromind.sandbox import Sandbox
from electromind.sandbox.tools import make_copy_to_host


@pytest.mark.asyncio
async def test_copy_to_host_exports_artifact_with_identical_content(tmp_path):
    """copy_to_host places the file in host artifacts with identical bytes."""
    workdir = tmp_path / "workspace"
    workdir.mkdir()
    host_root = tmp_path / "host"
    host_root.mkdir()

    # Create the source file in the sandbox workspace
    source = workdir / "result.dat"
    payload = ("# energy\n" + "SCF converged: -76.4321 Hartree\n" * 200).encode()
    source.write_bytes(payload)

    async with await Sandbox.create(
        backend="local",
        workdir=str(workdir),
        host_root=str(host_root),
    ) as box:
        tool = make_copy_to_host(box)
        out = await tool.acall(json.dumps({"source": "result.dat"}))

    assert out.ok, out.content
    artifacts_dir = host_root / "artifacts"
    assert artifacts_dir.is_dir(), "artifacts directory must exist"
    placed = artifacts_dir / "result.dat"
    assert placed.is_file(), "artifact file must exist"
    assert placed.read_bytes() == payload, (
        "exported artifact content must be byte-identical"
    )


@pytest.mark.asyncio
async def test_copy_to_host_export_and_wire_file_change(tmp_path):
    """End-to-end: agent writes → copy_to_host → artifact verified → the
    wire layer emits a FileChange event carrying thread/run identity."""
    from unittest.mock import patch

    from app import wire
    from app.config import ReplConfig

    workdir = tmp_path / "workspace"
    workdir.mkdir()
    host_root = tmp_path / "host"
    host_root.mkdir()

    async with await Sandbox.create(
        backend="local",
        workdir=str(workdir),
        host_root=str(host_root),
    ) as box:
        (workdir / "input.xyz").write_text("2\nwater\nO 0 0 0\nH 1 0 0\n")
        # Run a real agent turn whose tool writes the file
        from electromind.core.agent import Agent
        from electromind.core.provider import ProviderProtocol
        from electromind.runtime.runner import Runner

        events: list[dict] = []

        def capture(line: str):
            events.append(json.loads(line.strip()))

        class Provider(ProviderProtocol):
            async def complete(self, messages, tools=None, **kwargs):
                del messages, tools, kwargs
                tc = type(
                    "TC",
                    (),
                    {
                        "index": 0,
                        "id": "tc-write",
                        "type": "function",
                        "function": type(
                            "F",
                            (),
                            {
                                "name": "write_file",
                                "arguments": '{"path":"out.log","content":"ok"}',
                            },
                        )(),
                    },
                )()

                async def stream():
                    yield type(
                        "Chunk",
                        (),
                        {
                            "choices": [
                                type(
                                    "C",
                                    (),
                                    {"delta": type("D", (), {"tool_calls": [tc]})()},
                                )()
                            ]
                        },
                    )()

                return stream()

        thread_id = f"thread-export-{tmp_path.name}"
        session = wire._harness_manager._get_or_create(thread_id)
        session.active_run_id = "run-export-1"
        session.active_run_phase = "running"

        from electromind.runtime.thread import Thread
        from electromind.sandbox.tools import make_write_file

        thread = Thread.open(thread_id, overrides={"project_path": str(host_root)})
        write_tool = make_write_file(box)
        runner = Runner(
            thread=thread,
            sandbox=box,
            store=thread.open_store(),
            messages=thread.load_messages(),
            agent=Agent(Provider(), system="test", max_turns=1, tools=[write_tool]),
            skills=type("S", (), {"names": lambda: [], "list": lambda: []})(),
            conversation_id=thread.messages_conversation_id,
        )

        with (
            patch.object(wire, "emit_line", capture),
            patch.object(wire, "install_subagent_observer", lambda r, s: lambda: None),
            patch.object(wire, "log", lambda text: None),
        ):
            await wire.run_user_turn(
                runner,
                "write out.log",
                ReplConfig(permission_mode="auto"),
                {"turn": None, "thread_id": thread_id},
            )

    file_changes = [e for e in events if e.get("method") == "FileChange"]
    assert len(file_changes) >= 1, "write_file must emit a FileChange event"
    fc = file_changes[0]["params"]
    assert fc["path"] == "out.log"
    assert fc["thread_id"] == thread_id
    assert fc["run_id"] == "run-export-1"
    assert fc["tool_call_id"] == "tc-write"
    # The mutation tracker captures real before/after snapshots: the file
    # did not exist before → create with the actual content as additions.
    assert fc["status"] == "added"
    assert fc["additions"] == 1, "write_file content has 1 line"
    assert fc["deletions"] == 0
    assert fc["exact"] is True
    assert fc["before"]["exists"] is False
    assert fc["after"]["exists"] is True
    hunks = fc["hunks"]
    assert len(hunks) == 1, "real unified diff hunks must be present"
    addition_lines = [ln for ln in hunks[0]["lines"] if ln["kind"] == "addition"]
    assert addition_lines[0]["content"] == "ok", (
        "hunk must carry the ACTUAL written content, not placeholders"
    )

    # Artifact round-trip: the written file is exported and verified
    async def export_verify():
        async with await Sandbox.create(
            backend="local",
            workdir=str(workdir),
            host_root=str(host_root),
        ) as box2:
            tool = make_copy_to_host(box2)
            out = await tool.acall(json.dumps({"source": "out.log"}))
            assert out.ok
            placed = host_root / "artifacts" / "out.log"
            assert placed.read_text() == "ok"

    await export_verify()

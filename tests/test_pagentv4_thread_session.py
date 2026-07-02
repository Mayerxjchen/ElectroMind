import pytest

from pagentv4 import DeepSeek, Runner


@pytest.mark.asyncio
async def test_runner_open_local(tmp_path, monkeypatch):
    monkeypatch.setenv("PAGENT_THREADS_DIR", str(tmp_path))
    runner = await Runner.open(
        "demo",
        DeepSeek("deepseek-v4-flash", apikey="test-key"),
        overrides={"backend": "local", "model": "deepseek-v4-flash"},
        extra_system="你是 pagent 。",
        max_turns=8,
    )
    assert isinstance(runner, Runner)
    assert runner.thread.created is True
    assert runner.agent.max_turns == 8
    assert runner.sandbox.workdir == str(tmp_path / "demo" / "workspace")
    assert runner.messages.data == []
    await runner.close()

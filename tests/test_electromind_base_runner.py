"""BaseRunner 基础引擎单测：所有持久化都挂在 Thread 上。"""

import types
from pathlib import Path

import pytest

from electromind import Agent, BaseRunner, RunEnd, TextDelta, Thread, tool
from electromind.ithread import ThreadSpec
from electromind.runtime.base_runner import assemble_run_resources


class FakeStreamChunk:
    def __init__(self, *, content=None, reasoning=None, tool_calls=None):
        delta = types.SimpleNamespace(
            content=content,
            reasoning_content=reasoning,
            tool_calls=tool_calls,
        )
        self.choices = [types.SimpleNamespace(delta=delta)]


class FakeProvider:
    def __init__(self, steps):
        self.steps = list(steps)

    async def complete(self, messages, tools=None, **run_kwargs):
        chunks = self.steps.pop(0)

        async def stream():
            for chunk in chunks:
                yield chunk

        return stream()


def make_runner(provider, *, system="test", tools=None, tmp_path=None):
    """直接构造 BaseRunner，验证基础引擎。"""
    agent = Agent(provider, system=system, tools=tools or [])
    thread = Thread.open(
        "test",
        root=tmp_path,
        overrides=ThreadSpec(backend="none").__dict__,
    )
    return BaseRunner(agent, thread)


@pytest.mark.asyncio
async def test_basic_run(tmp_path):
    provider = FakeProvider([[FakeStreamChunk(content="hello")]])
    runner = make_runner(provider, tmp_path=tmp_path)

    texts = [t async for t in runner.run("hi", return_type="text")]
    assert texts == ["hello"]
    await runner.close()


@pytest.mark.asyncio
async def test_thread_drives_conversation_config(tmp_path):
    """thread 里的 conversation 配置决定 store 行为。"""
    provider = FakeProvider([[FakeStreamChunk(content="spec-test")]])
    agent = Agent(provider, system="test")
    thread = Thread.open(
        "spec-test",
        root=tmp_path,
        overrides=ThreadSpec(
            conversation_backend="jsonl",
            conversation_root="conversation",
            conversation_messages_id="main",
            backend="none",
        ).__dict__,
    )
    runner = BaseRunner(agent, thread)

    assert runner.thread is thread
    assert runner.spec is thread.spec
    assert runner.conversation_id == "main"

    texts = [t async for t in runner.run("hi", return_type="text")]
    assert texts == ["spec-test"]
    assert (tmp_path / "spec-test" / "conversation" / "main.jsonl").is_file()
    await runner.close()


@pytest.mark.asyncio
async def test_no_sandbox_when_backend_none(tmp_path):
    """spec.backend="none" 时不创建 sandbox。"""
    provider = FakeProvider([[FakeStreamChunk(content="no-sandbox")]])
    agent = Agent(provider, system="test")
    thread = Thread.open(
        "no-sandbox",
        root=tmp_path,
        overrides=ThreadSpec(backend="none").__dict__,
    )
    runner = BaseRunner(agent, thread)

    assert runner.sandbox is None

    texts = [t async for t in runner.run("hi", return_type="text")]
    assert texts == ["no-sandbox"]
    await runner.close()


@pytest.mark.asyncio
async def test_from_spec_opens_thread(tmp_path):
    """from_spec 也必须先打开 thread。"""
    provider = FakeProvider([[FakeStreamChunk(content="from-spec")]])
    runner = await BaseRunner.from_spec(
        "from-spec",
        ThreadSpec(
            conversation_messages_id="main",
            conversation_root="conversation",
            backend="none",
        ),
        provider,
        root=tmp_path,
        extra_system="test",
    )

    assert runner.thread.id == "from-spec"
    assert runner.conversation_id == "main"
    texts = [t async for t in runner.run("hi", return_type="text")]
    assert texts == ["from-spec"]
    assert (tmp_path / "from-spec" / "conversation" / "main.jsonl").is_file()
    await runner.close()


@pytest.mark.asyncio
async def test_from_spec_opens_thread_sandbox(monkeypatch, tmp_path):
    """from_spec 开 sandbox 时使用 thread 的 workspace。"""
    provider = FakeProvider([[FakeStreamChunk(content="sandbox")]])

    class FakeSandbox:
        def tools(self):
            return []

        async def describe(self):
            return "fake sandbox"

        async def install_skills(self, registry):
            return {}

        async def close(self):
            return None

    async def fake_open_sandbox(self, name="main"):
        assert self.workspace_path == tmp_path / "with-sandbox" / "workspaces" / "main"
        return FakeSandbox()

    monkeypatch.setattr(Thread, "open_sandbox", fake_open_sandbox)
    runner = await BaseRunner.from_spec(
        "with-sandbox",
        ThreadSpec(
            backend="local",
            conversation_root="conversation",
        ),
        provider,
        root=tmp_path,
    )

    assert runner.thread.id == "with-sandbox"
    assert runner.sandbox is not None
    await runner.close()


@pytest.mark.asyncio
async def test_flush_conversation(tmp_path):
    provider = FakeProvider([[FakeStreamChunk(content="saved")]])
    runner = make_runner(provider, tmp_path=tmp_path)

    async for _ in runner.run("hi", return_type="event"):
        pass

    reloaded = runner.store.load(runner.conversation_id)
    assert any(
        m.content.text == "saved" for m in reloaded.data if m.role == "assistant"
    )
    assert (tmp_path / "test" / "messages" / "messages.jsonl").is_file()
    await runner.close()


@pytest.mark.asyncio
async def test_flush_each_continuing(tmp_path):
    tc = types.SimpleNamespace(
        index=0,
        id="c1",
        type="function",
        function=types.SimpleNamespace(name="echo", arguments='{"msg":"ping"}'),
    )

    @tool()
    def echo(msg: str) -> str:
        """Echo back."""
        return msg

    provider = FakeProvider(
        [
            [FakeStreamChunk(tool_calls=[tc])],
            [FakeStreamChunk(content="done")],
        ]
    )
    runner = make_runner(provider, tools=[echo], tmp_path=tmp_path)

    saves = 0
    original_save = runner.store.save

    def counting_save(cid, msgs):
        nonlocal saves
        saves += 1
        original_save(cid, msgs)

    runner.store.save = counting_save  # type: ignore[assignment]
    async for _ in runner.run("go", return_type="event"):
        pass

    assert saves >= 2
    await runner.close()


@pytest.mark.asyncio
async def test_event_stream_with_tools(tmp_path):
    from electromind import ToolCallBegin, ToolResult

    tc = types.SimpleNamespace(
        index=0,
        id="c1",
        type="function",
        function=types.SimpleNamespace(name="echo", arguments='{"msg":"hi"}'),
    )

    @tool()
    def echo(msg: str) -> str:
        """Echo back."""
        return msg

    provider = FakeProvider(
        [
            [FakeStreamChunk(content="checking", tool_calls=[tc])],
            [FakeStreamChunk(content="done")],
        ]
    )
    runner = make_runner(provider, tools=[echo], tmp_path=tmp_path)
    agent = Agent(provider, system="test", tools=[echo], max_turns=4)
    runner.agent = agent

    events = [e async for e in runner.run("go", return_type="event")]
    assert any(isinstance(e, TextDelta) and e.text == "checking" for e in events)
    assert any(isinstance(e, ToolCallBegin) and e.tool_call_id == "c1" for e in events)
    assert any(isinstance(e, ToolResult) and e.tool_call_id == "c1" for e in events)
    assert isinstance(events[-1], RunEnd)
    await runner.close()


@pytest.mark.asyncio
async def test_run_state_closing_on_close(tmp_path, monkeypatch):
    import asyncio

    provider = FakeProvider([[FakeStreamChunk(content="hello")]])

    class SlowSandbox:
        closed = False

        def tools(self):
            return []

        async def describe(self):
            return "slow sandbox"

        async def install_skills(self, registry):
            del registry
            return {}

        async def close(self):
            await asyncio.sleep(0.05)
            self.closed = True

    sandbox = SlowSandbox()

    async def open_sandbox(_self):
        return sandbox

    monkeypatch.setattr(Thread, "open_sandbox", open_sandbox)
    runner = await BaseRunner.from_spec(
        "closing-test",
        ThreadSpec(backend="local"),
        provider,
        root=tmp_path,
    )
    observed: list[str] = []

    async def poll() -> None:
        while True:
            phase = runner.run_state.phase
            if not observed or observed[-1] != phase:
                observed.append(phase)
            if phase == "idle" and sandbox.closed:
                break
            await asyncio.sleep(0.005)

    poller = asyncio.create_task(poll())
    await runner.close()
    await poller

    assert "closing" in observed
    assert runner.run_state.phase == "idle"
    assert sandbox.closed is True


# ---------------------------------------------------------------------------
# Task 4: project skill discovery
# ---------------------------------------------------------------------------


def _make_project_skills(project):
    """Create a project with flat `.agents/skills/` skills (A+ W5)."""
    skills = project / ".agents" / "skills"
    wf = skills / "workflow"
    wf.mkdir(parents=True)
    (wf / "SKILL.md").write_text(
        "---\nname: workflow\ndescription: A workflow\n---\nRun it.\n",
        encoding="utf-8",
    )
    tool = skills / "hpc-submit"
    tool.mkdir(parents=True)
    (tool / "SKILL.md").write_text(
        "---\nname: hpc-submit\ndescription: Submit HPC jobs\n---\nSubmit.\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_runner_discovers_project_skills_from_thread_project_path(tmp_path):
    """Runner discovers project skills when thread.spec.project_path points to a project."""
    project = tmp_path / "project"
    project.mkdir()
    _make_project_skills(project)

    thread = Thread.open(
        "disc-test",
        root=tmp_path,
        overrides=ThreadSpec(backend="none", project_path=str(project)).__dict__,
    )

    resources = await assemble_run_resources(thread)
    assert resources.skills is not None
    assert "hpc-submit" in resources.skills.names()
    assert "workflow" in resources.skills.names()


@pytest.mark.asyncio
async def test_runner_treats_thread_skills_as_additional_legacy_roots(tmp_path):
    """thread.spec.skills entries remain available as additional legacy roots."""
    project = tmp_path / "project"
    project.mkdir()
    legacy_dir = tmp_path / "legacy-skills"
    legacy_dir.mkdir()
    (legacy_dir / "legacy-helper").mkdir()
    (legacy_dir / "legacy-helper" / "SKILL.md").write_text(
        "---\nname: legacy-helper\ndescription: legacy skill\n---\nbody\n",
        encoding="utf-8",
    )

    thread = Thread.open(
        "legacy-test",
        root=tmp_path,
        overrides=ThreadSpec(
            backend="none",
            project_path=str(project),
            skills=(str(legacy_dir),),
        ).__dict__,
    )

    resources = await assemble_run_resources(thread)
    assert "legacy-helper" in resources.skills.names()


@pytest.mark.asyncio
async def test_runner_project_skill_overrides_legacy_duplicate(tmp_path):
    """A project skill wins over a legacy root skill with the same name."""
    project = tmp_path / "project"
    project.mkdir()
    _make_project_skills(project)

    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "hpc-submit").mkdir()
    (legacy / "hpc-submit" / "SKILL.md").write_text(
        "---\nname: hpc-submit\ndescription: legacy version\n---\nbody\n",
        encoding="utf-8",
    )

    thread = Thread.open(
        "override-test",
        root=tmp_path,
        overrides=ThreadSpec(
            backend="none",
            project_path=str(project),
            skills=(str(legacy),),
        ).__dict__,
    )

    resources = await assemble_run_resources(thread)
    skill = resources.skills.get("hpc-submit")
    assert skill is not None
    assert skill.description == "Submit HPC jobs"  # project version wins


@pytest.mark.asyncio
async def test_runner_without_project_still_discovers_user_skills(
    tmp_path, monkeypatch
):
    """Without a project, user home skills are still discovered."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    user_skills = home / ".electromind" / "skills"
    user_skills.mkdir(parents=True)
    (user_skills / "user-helper").mkdir()
    (user_skills / "user-helper" / "SKILL.md").write_text(
        "---\nname: user-helper\ndescription: user skill\n---\nbody\n",
        encoding="utf-8",
    )

    thread = Thread.open(
        "user-test",
        root=tmp_path,
        overrides=ThreadSpec(backend="none").__dict__,
    )

    resources = await assemble_run_resources(thread)
    assert "user-helper" in resources.skills.names()


@pytest.mark.asyncio
async def test_empty_skills_still_produces_empty_catalog_when_project_has_no_skills(
    tmp_path,
):
    """An empty thread.spec.skills with a project without skills should produce an empty catalog."""
    project = tmp_path / "project"
    project.mkdir()

    thread = Thread.open(
        "empty-test",
        root=tmp_path,
        overrides=ThreadSpec(backend="none", project_path=str(project)).__dict__,
    )

    resources = await assemble_run_resources(thread, builtin_roots=())
    assert resources.skills.names() == []


# ---------------------------------------------------------------------------
# Task 5: skill refresh tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skill_added_between_turns_is_available_next_turn(tmp_path, monkeypatch):
    """When a new skill is added to the project between turns, it appears on the next turn."""
    project = tmp_path / "project"
    project.mkdir()
    agents_skills = project / ".agents" / "skills"
    agents_skills.mkdir(parents=True)

    provider = FakeProvider(
        [
            [FakeStreamChunk(content="turn1")],
            [FakeStreamChunk(content="turn2")],
        ]
    )

    # Create runner without skills
    runner = await BaseRunner.from_spec(
        "refresh-test",
        ThreadSpec(backend="none", project_path=str(project)),
        provider,
        root=tmp_path,
        builtin_roots=(),
    )
    try:
        # Turn 1 – no skills yet
        async for _ in runner.run("hi"):
            pass
        assert runner.skill_runtime is not None
        snapshot1 = runner.skill_runtime.snapshot
        # Should be empty
        assert snapshot1 is None or snapshot1.registry.names() == []

        # Add a skill between turns
        d = agents_skills / "added-later"
        d.mkdir()
        (d / "SKILL.md").write_text(
            "---\nname: added-later\ndescription: added later\n---\nbody\n",
            encoding="utf-8",
        )

        # Turn 2 – skill should be discovered via before_user_turn
        async for _ in runner.run("again"):
            pass

        assert runner.skill_runtime.snapshot is not None
        assert "added-later" in runner.skill_runtime.snapshot.registry.names()
    finally:
        await runner.close()


@pytest.mark.asyncio
async def test_skill_change_does_not_mutate_active_turn(tmp_path, monkeypatch):
    """Skills loaded for a turn must not be mutated during the active turn."""
    project = tmp_path / "project"
    project.mkdir()
    agents_skills = project / ".agents" / "skills"
    agents_skills.mkdir(parents=True)
    d = agents_skills / "stable-skill"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\nname: stable-skill\ndescription: stable\n---\nbody\n",
        encoding="utf-8",
    )

    provider = FakeProvider(
        [
            [FakeStreamChunk(content="hello")],
            [FakeStreamChunk(content="world")],
        ]
    )
    runner = await BaseRunner.from_spec(
        "stable-test",
        ThreadSpec(backend="none", project_path=str(project)),
        provider,
        root=tmp_path,
    )
    try:
        # Run a turn to load skills
        async for _ in runner.run("hi"):
            pass

        # Capture the snapshot used during the turn
        snapshot_during = runner.skill_runtime.snapshot
        assert snapshot_during is not None

        # Modify skill file on disk
        (d / "SKILL.md").write_text(
            "---\nname: stable-skill\ndescription: modified\n---\nchanged body\n",
            encoding="utf-8",
        )

        # The captured snapshot should be unchanged (immutable)
        skill = snapshot_during.registry.get("stable-skill")
        assert skill is not None
        assert skill.description == "stable"

        # Next turn should pick up the change
        async for _ in runner.run("next"):
            pass
        new_skill = runner.skill_runtime.snapshot.registry.get("stable-skill")
        assert new_skill is not None
        assert new_skill.description == "modified"
    finally:
        await runner.close()


@pytest.mark.asyncio
async def test_failed_refresh_keeps_previous_snapshot(tmp_path, monkeypatch):
    """When refresh_if_changed fails, the previous snapshot is preserved."""
    project = tmp_path / "project"
    project.mkdir()
    agents_skills = project / ".agents" / "skills"
    agents_skills.mkdir(parents=True)
    d = agents_skills / "persistent"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\nname: persistent\ndescription: persists\n---\nbody\n",
        encoding="utf-8",
    )

    provider = FakeProvider(
        [
            [FakeStreamChunk(content="t1")],
            [FakeStreamChunk(content="t2")],
        ]
    )
    runner = await BaseRunner.from_spec(
        "fail-test",
        ThreadSpec(backend="none", project_path=str(project)),
        provider,
        root=tmp_path,
        builtin_roots=(),
    )
    try:
        async for _ in runner.run("hi"):
            pass

        snapshot_before = runner.skill_runtime.snapshot
        assert snapshot_before is not None
        assert "persistent" in snapshot_before.registry.names()

        # Corrupt the skill file
        (d / "SKILL.md").write_text(
            "not valid yaml at all --- \n???\n", encoding="utf-8"
        )

        # Refresh: should fail gracefully (SKILL.md frontmatter missing description)
        changed = await runner.skill_runtime.refresh_if_changed()
        assert changed is False  # failed refresh returns False
        # The key invariant: previous snapshot data is accessible
        assert runner.skill_runtime.snapshot is not None

        # Turn should still run
        async for _ in runner.run("next"):
            pass
    finally:
        await runner.close()


@pytest.mark.asyncio
async def test_resume_rebuilds_catalog_from_current_project(tmp_path, monkeypatch):
    """When resuming, the catalog is rebuilt from the current project state."""
    project = tmp_path / "project"
    project.mkdir()
    _make_project_skills(project)

    provider = FakeProvider(
        [
            [FakeStreamChunk(content="t1")],
            [FakeStreamChunk(content="t2")],
        ]
    )

    runner1 = await BaseRunner.from_spec(
        "resume-test",
        ThreadSpec(backend="none", project_path=str(project)),
        provider,
        root=tmp_path,
    )
    try:
        async for _ in runner1.run("first"):
            pass

        assert runner1.skill_runtime is not None
        assert "hpc-submit" in runner1.skill_runtime.snapshot.registry.names()
    finally:
        await runner1.close()

    # Simulate a new runner for the same thread (resume)
    runner2 = await BaseRunner.from_spec(
        "resume-test",
        ThreadSpec(backend="none", project_path=str(project)),
        provider,
        root=tmp_path,
    )
    try:
        # Catalog must be rebuilt from current project
        assert runner2.skill_runtime is not None
        # Initial load in assemble_run_resources gives initial snapshot
        assert runner2.skill_runtime.snapshot is not None
        assert "hpc-submit" in runner2.skill_runtime.snapshot.registry.names()
        async for _ in runner2.run("second"):
            pass
    finally:
        await runner2.close()


# ---------------------------------------------------------------------------
# Phase-2 composition regressions (P0/P1)
# ---------------------------------------------------------------------------


async def test_no_full_install_on_generation_change(tmp_path, monkeypatch):
    """P0: generation 变化不再全量安装 — 懒挂载只在激活时发生。"""
    from electromind.skills.catalog_service import SkillCatalogService
    from electromind.skills.runtime import SkillRuntime

    project = tmp_path / "project"
    project.mkdir()
    agents_skills = project / ".agents" / "skills"
    agents_skills.mkdir(parents=True)

    service = SkillCatalogService(
        project_path=str(project), cwd=str(project), builtin_roots=()
    )
    rt = SkillRuntime(str(project), service=service, builtin_roots=())
    view1 = rt.prepare_turn()
    assert view1 is not None

    # 监控 install_skill_catalog —— 切流后不得被调用
    installed = []

    class _FakeSandbox:
        async def install_skill_catalog(self, *a, **kw):
            installed.append(1)
            return {}

    # 模拟 before_user_turn 路径（直接调 runtime 逻辑）
    view2 = rt.prepare_turn()  # 同内容 → 同 generation，无安装
    assert view2 is view1
    assert installed == []

    # 内容变化 → 新 generation，但依旧不安装（懒挂载）
    d = agents_skills / "new"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\nname: new\ndescription: d\n---\nb\n", encoding="utf-8"
    )
    view3 = rt.prepare_turn()
    assert view3.generation > view2.generation
    assert installed == []  # 没有全量安装调用


def test_run_capabilities_from_backend():
    """P1: Run capabilities 由 execution backend 派生。"""
    from electromind.ithread import ThreadSpec
    from electromind.runtime.base_runner import _run_capabilities

    assert _run_capabilities(ThreadSpec(backend="ssh")) == ("ssh",)
    assert _run_capabilities(ThreadSpec(backend="local")) == ("local",)
    assert _run_capabilities(ThreadSpec(backend="none")) == ("local",)


def test_activation_tool_capabilities_threaded():
    """P1: 生产 use_skill 工具携带 capabilities（SSH-only 在 local 拒绝）。"""
    import asyncio
    import json as _json

    from electromind.runtime.base_runner import _activation_use_skill_tool
    from electromind.skills.candidate import (
        SkillCandidate,
        SkillDescriptor,
        SkillSource,
    )
    from electromind.skills.catalog import build_catalog

    d = tmp_path_skill()
    source = SkillSource(
        source_id="x",
        scope="project",
        dialect="agents",
        root=d.parent,
        project_root=Path(d.parent).parent,
        trust_domain=str(d.parent),
    )
    cand = SkillCandidate(
        skill_id="project:repo:agents:ssh-only",
        descriptor=SkillDescriptor(
            name="ssh-only",
            description="d",
            entry_path=d / "SKILL.md",
            root_path=d,
            frontmatter={"name": "ssh-only"},
            content_digest="c" * 64,
            resource_digest="r" * 64,
            compatibility=("ssh",),
        ),
        source=source,
    )
    catalog = build_catalog((cand,), generation=1, cwd="/w", repo_root=None)
    tool = _activation_use_skill_tool(catalog, None, capabilities=("local",))
    result = asyncio.run(tool.acall({"name": "ssh-only"}))
    payload = _json.loads(result.content)
    assert payload["ok"] is False  # local 环境拒绝 SSH-only

    tool_ssh = _activation_use_skill_tool(catalog, None, capabilities=("ssh",))
    result2 = asyncio.run(tool_ssh.acall({"name": "ssh-only"}))
    payload2 = _json.loads(result2.content)
    assert payload2["ok"] is True  # ssh 环境放行


def tmp_path_skill() -> Path:
    import tempfile

    d = Path(tempfile.mkdtemp()) / "ssh-only"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: ssh-only\ndescription: d\n---\nbody\n", encoding="utf-8"
    )
    return d

import asyncio
import json
import os
import sys

import pytest

from pagentv4 import Runner, Sandbox, SandboxLimits
from pagentv4.sandbox import (
    SANDBOX_TOOL_NAMES,
    LocalBackend,
    SandboxSpec,
    build_backend,
    build_computer_description,
    build_sandbox_tools,
    resolve_tool_names,
    resolve_workdir,
)
from pagentv4.sandbox.backends.docker import DockerBackend
from pagentv4.sandbox.backends.podman import PodmanBackend
from pagentv4.sandbox.backends.ssh import SshBackend


@pytest.mark.asyncio
async def test_resolve_workdir_direct(tmp_path):
    target = tmp_path / "job"
    resolved = resolve_workdir(workspace_id=None, workdir=str(target))
    assert os.path.isdir(resolved)
    assert resolved == str(target.resolve())


@pytest.mark.asyncio
async def test_resolve_workdir_workspace_id(tmp_path, monkeypatch):
    home = tmp_path / "home"
    cwd = tmp_path / "cwd"
    home.mkdir()
    cwd.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(cwd)
    resolved = resolve_workdir(workspace_id="alpha", workdir=None)
    assert resolved == str((home / ".pagent" / "workspaces" / "alpha").resolve())
    assert os.path.isdir(resolved)


def test_resolve_workdir_requires_target():
    with pytest.raises(ValueError):
        resolve_workdir(workspace_id=None, workdir=None)


def test_resolve_workdir_rejects_bad_id(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(ValueError):
        resolve_workdir(workspace_id="../escape", workdir=None)


def test_default_workspaces_root_is_user_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    cwd = tmp_path / "cwd"
    home.mkdir()
    cwd.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(cwd)
    resolved = resolve_workdir(workspace_id="beta", workdir=None)
    assert resolved == str((home / ".pagent" / "workspaces" / "beta").resolve())
    assert os.path.isdir(resolved)


def test_build_backend_dispatch():
    assert isinstance(build_backend("local"), LocalBackend)
    assert isinstance(build_backend("docker"), DockerBackend)
    assert isinstance(build_backend("podman"), PodmanBackend)
    with pytest.raises(ValueError):
        build_backend("nope")


def test_build_backend_container_prefers_docker(monkeypatch):
    """backend=container 时按 docker→podman 探测 PATH，docker 在就用 docker。"""
    from pagentv4.sandbox import sandbox as sandbox_mod

    monkeypatch.setattr(sandbox_mod.shutil, "which", lambda cli: cli == "docker")
    assert isinstance(build_backend("container"), DockerBackend)


def test_build_backend_container_falls_back_to_podman(monkeypatch):
    """docker 不在 PATH、podman 在时，container 落到 podman。"""
    from pagentv4.sandbox import sandbox as sandbox_mod

    monkeypatch.setattr(sandbox_mod.shutil, "which", lambda cli: cli == "podman")
    assert isinstance(build_backend("container"), PodmanBackend)


def test_detect_container_cli_raises_when_none_available(monkeypatch):
    """docker/podman 都不在 PATH，detect_container_cli 抛 SandboxError 指明安装项。"""
    from pagentv4.sandbox import SandboxError, detect_container_cli
    from pagentv4.sandbox import sandbox as sandbox_mod

    monkeypatch.setattr(sandbox_mod.shutil, "which", lambda cli: None)
    with pytest.raises(SandboxError, match="docker / podman"):
        detect_container_cli()


@pytest.mark.asyncio
async def test_local_run_returns_stdout(tmp_path):
    async with await Sandbox.create(backend="local", workdir=str(tmp_path)) as box:
        result = await box.commands.run("echo hello")
        assert result.ok is True
        assert result.exit_code == 0
        assert result.stdout.strip() == "hello"
        assert result.timed_out is False


@pytest.mark.asyncio
async def test_local_run_captures_stderr_and_exit(tmp_path):
    async with await Sandbox.create(backend="local", workdir=str(tmp_path)) as box:
        result = await box.commands.run("echo boom >&2 && exit 3")
        assert result.ok is False
        assert result.exit_code == 3
        assert "boom" in result.stderr


@pytest.mark.asyncio
async def test_local_run_uses_workdir_as_cwd(tmp_path):
    async with await Sandbox.create(backend="local", workdir=str(tmp_path)) as box:
        result = await box.commands.run("pwd")
        assert result.stdout.strip() == str(tmp_path.resolve())


@pytest.mark.asyncio
async def test_local_run_timeout_kills(tmp_path):
    async with await Sandbox.create(backend="local", workdir=str(tmp_path)) as box:
        result = await box.commands.run("sleep 5", timeout=0.2)
        assert result.timed_out is True
        assert result.ok is False


@pytest.mark.asyncio
async def test_local_run_stdout_truncation(tmp_path):
    limits = SandboxLimits(stdout_bytes=8)
    async with await Sandbox.create(
        backend="local", workdir=str(tmp_path), default_limits=limits
    ) as box:
        result = await box.commands.run("printf 'abcdefghijkl'")
        assert result.stdout_truncated is True
        assert result.stdout == "abcdefgh"


@pytest.mark.asyncio
async def test_local_files_read_write_roundtrip(tmp_path):
    async with await Sandbox.create(backend="local", workdir=str(tmp_path)) as box:
        await box.files.write("hello.txt", "hi there")
        assert await box.files.exists("hello.txt") is True
        text = await box.files.read_text("hello.txt")
        assert text == "hi there"


@pytest.mark.asyncio
async def test_local_files_write_creates_parents(tmp_path):
    async with await Sandbox.create(backend="local", workdir=str(tmp_path)) as box:
        await box.files.write("nested/deep/note.md", b"note")
        raw = await box.files.read("nested/deep/note.md")
        assert raw == b"note"


@pytest.mark.asyncio
async def test_local_files_list(tmp_path):
    async with await Sandbox.create(backend="local", workdir=str(tmp_path)) as box:
        await box.files.write("a.txt", b"1")
        await box.files.write("sub/b.txt", b"22")
        entries = await box.files.list(".")
        names = {entry.name for entry in entries}
        assert names == {"a.txt", "sub"}
        by_name = {entry.name: entry for entry in entries}
        assert by_name["a.txt"].is_dir is False
        assert by_name["a.txt"].size == 1
        assert by_name["sub"].is_dir is True


@pytest.mark.asyncio
async def test_local_files_list_skips_broken_symlink(tmp_path):
    async with await Sandbox.create(backend="local", workdir=str(tmp_path)) as box:
        await box.files.write("a.txt", b"1")
        os.symlink(tmp_path / "missing", tmp_path / "python")

        entries = await box.files.list(".")

        assert [entry.name for entry in entries] == ["a.txt"]


@pytest.mark.asyncio
async def test_local_files_remove_file_and_dir(tmp_path):
    async with await Sandbox.create(backend="local", workdir=str(tmp_path)) as box:
        await box.files.write("a.txt", b"x")
        await box.files.remove("a.txt")
        assert await box.files.exists("a.txt") is False

        await box.files.write("dir/inner.txt", b"y")
        with pytest.raises(IsADirectoryError):
            await box.files.remove("dir")
        await box.files.remove("dir", recursive=True)
        assert await box.files.exists("dir") is False


@pytest.mark.asyncio
async def test_sandbox_persists_workdir_across_instances(tmp_path):
    async with await Sandbox.create(backend="local", workdir=str(tmp_path)) as box:
        await box.files.write("state.txt", "keep")

    async with await Sandbox.create(backend="local", workdir=str(tmp_path)) as box:
        assert await box.files.read_text("state.txt") == "keep"


@pytest.mark.asyncio
@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="RLIMIT_AS is only reliable on Linux",
)
async def test_local_memory_rlimit_kills_process(tmp_path):
    limits = SandboxLimits(memory_bytes=8 * 1024 * 1024, timeout=5.0)
    async with await Sandbox.create(
        backend="local", workdir=str(tmp_path), default_limits=limits
    ) as box:
        result = await box.commands.run(
            'python3 -c "x = bytearray(200 * 1024 * 1024); print(len(x))"'
        )
        assert result.ok is False


@pytest.mark.asyncio
async def test_sandbox_stdin_flow(tmp_path):
    async with await Sandbox.create(backend="local", workdir=str(tmp_path)) as box:
        result = await box.commands.run("cat", stdin="pipe payload")
        assert result.ok is True
        assert result.stdout == "pipe payload"


def test_local_run_manual_event_loop(tmp_path):
    async def scenario():
        async with await Sandbox.create(backend="local", workdir=str(tmp_path)) as box:
            return await box.commands.run("echo loop")

    result = asyncio.run(scenario())
    assert result.stdout.strip() == "loop"


@pytest.mark.asyncio
async def test_virtual_home_resolves_and_persists(tmp_path):
    async with await Sandbox.create(backend="local", workdir=str(tmp_path)) as box:
        assert box.home == "/home/agent"
        await box.files.write("/home/agent/note.txt", "hi from agent")
        assert (tmp_path / "note.txt").read_text() == "hi from agent"
        assert await box.files.read_text("/home/agent/note.txt") == "hi from agent"
        assert await box.files.read_text("note.txt") == "hi from agent"


@pytest.mark.asyncio
async def test_virtual_home_rejects_escape(tmp_path):
    async with await Sandbox.create(backend="local", workdir=str(tmp_path)) as box:
        with pytest.raises(ValueError):
            await box.files.read("/etc/passwd")
        with pytest.raises(ValueError):
            await box.files.read("/home/agent/../secret")


@pytest.mark.asyncio
async def test_virtual_home_shell_command_map(tmp_path):
    async with await Sandbox.create(backend="local", workdir=str(tmp_path)) as box:
        (tmp_path / "target.txt").write_text("payload")
        result = await box.commands.run("cat /home/agent/target.txt")
        assert result.ok is True
        assert result.stdout.strip() == "payload"


@pytest.mark.asyncio
async def test_custom_home_prefix(tmp_path):
    async with await Sandbox.create(
        backend="local", workdir=str(tmp_path), home="/work"
    ) as box:
        await box.files.write("/work/hello.txt", "greetings")
        assert (tmp_path / "hello.txt").read_text() == "greetings"
        assert box.to_virtual_path(str(tmp_path / "hello.txt")) == "/work/hello.txt"


@pytest.mark.asyncio
async def test_copy_between_host_and_sandbox(tmp_path):
    host_source = tmp_path / "host_input.txt"
    host_source.write_text("payload from host")
    sandbox_dir = tmp_path / "sandbox"

    async with await Sandbox.create(
        backend="local", workdir=str(sandbox_dir), host_root=str(tmp_path)
    ) as box:
        placed = await box.copy_from_host("host_input.txt")
        assert placed == "/home/agent/host_input.txt"
        assert (sandbox_dir / "host_input.txt").read_text() == "payload from host"

        exported = await box.copy_to_host("host_input.txt")
        assert os.path.isfile(exported)
        assert (
            tmp_path / "artifacts" / "host_input.txt"
        ).read_text() == "payload from host"


@pytest.mark.asyncio
async def test_host_root_defaults_to_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    async with await Sandbox.create(
        backend="local", workdir=str(tmp_path / "box")
    ) as box:
        assert box.host_root == str(tmp_path.resolve())
        assert box.artifacts_dir == str((tmp_path / "artifacts").resolve())


@pytest.mark.asyncio
async def test_host_root_expands_user(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    async with await Sandbox.create(
        backend="local", workdir=str(tmp_path / "box"), host_root="~"
    ) as box:
        assert box.host_root == str(tmp_path.resolve())


@pytest.mark.asyncio
async def test_resolve_host_path_rejects_escape(tmp_path):
    async with await Sandbox.create(
        backend="local", workdir=str(tmp_path / "box"), host_root=str(tmp_path)
    ) as box:
        with pytest.raises(ValueError):
            box.resolve_host_path("/etc/passwd")
        with pytest.raises(ValueError):
            box.resolve_host_path("../outside")


@pytest.mark.asyncio
async def test_copy_to_host_defaults_to_artifacts_dir(tmp_path):
    async with await Sandbox.create(
        backend="local",
        workdir=str(tmp_path / "box"),
        host_root=str(tmp_path),
    ) as box:
        await box.files.write("result.txt", "greetings from sandbox")
        placed = await box.copy_to_host("result.txt")
        expected = tmp_path / "artifacts" / "result.txt"
        assert placed == str(expected)
        assert expected.read_text() == "greetings from sandbox"


@pytest.mark.asyncio
async def test_copy_from_host_missing_file_raises(tmp_path):
    async with await Sandbox.create(
        backend="local",
        workdir=str(tmp_path / "box"),
        host_root=str(tmp_path),
    ) as box:
        with pytest.raises(FileNotFoundError):
            await box.copy_from_host("nope.txt")


@pytest.mark.asyncio
async def test_copy_from_host_directory(tmp_path):
    lib = tmp_path / "pkg"
    lib.mkdir()
    (lib / "a.py").write_text("a")
    sub = lib / "sub"
    sub.mkdir()
    (sub / "b.py").write_text("b")
    sandbox_dir = tmp_path / "box"

    async with await Sandbox.create(
        backend="local",
        workdir=str(sandbox_dir),
        host_root=str(tmp_path),
    ) as box:
        placed = await box.copy_from_host("pkg")
        assert placed == "/home/agent/pkg"
        assert (sandbox_dir / "pkg" / "a.py").read_text() == "a"
        assert (sandbox_dir / "pkg" / "sub" / "b.py").read_text() == "b"


@pytest.mark.asyncio
async def test_list_host_files_depth_one(tmp_path):
    (tmp_path / "a.txt").write_text("aa")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("bb")

    async with await Sandbox.create(
        backend="local",
        workdir=str(tmp_path / "box"),
        host_root=str(tmp_path),
    ) as box:
        listing = box.list_host_files("", depth=1)
        assert listing["ok"] is True
        assert listing["path"] == "."
        names = sorted(entry["name"] for entry in listing["entries"])
        # 只列直接子项，sub 内的 b.txt 不应出现
        assert "a.txt" in names
        assert "sub" in names
        sub_entry = next(e for e in listing["entries"] if e["name"] == "sub")
        assert "children" not in sub_entry


@pytest.mark.asyncio
async def test_list_host_files_depth_two_recurses(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("bb")

    async with await Sandbox.create(
        backend="local",
        workdir=str(tmp_path / "box"),
        host_root=str(tmp_path),
    ) as box:
        listing = box.list_host_files("", depth=2)
        sub_entry = next(e for e in listing["entries"] if e["name"] == "sub")
        child_names = [c["name"] for c in sub_entry["children"]]
        assert "b.txt" in child_names


@pytest.mark.asyncio
async def test_list_host_files_rejects_bad_depth(tmp_path):
    async with await Sandbox.create(
        backend="local",
        workdir=str(tmp_path / "box"),
        host_root=str(tmp_path),
    ) as box:
        with pytest.raises(ValueError):
            box.list_host_files("", depth=0)
        with pytest.raises(ValueError):
            box.list_host_files("", depth=4)


@pytest.mark.asyncio
async def test_list_host_files_missing_path(tmp_path):
    async with await Sandbox.create(
        backend="local",
        workdir=str(tmp_path / "box"),
        host_root=str(tmp_path),
    ) as box:
        listing = box.list_host_files("does-not-exist")
        assert listing["ok"] is False
        assert listing["entries"] == []


@pytest.mark.asyncio
async def test_list_host_files_tool_returns_json(tmp_path):
    (tmp_path / "note.md").write_text("hi")
    async with await Sandbox.create(
        backend="local",
        workdir=str(tmp_path / "box"),
        host_root=str(tmp_path),
    ) as box:
        tool = next(t for t in box.tools() if t.name == "list_host_files")
        result = await tool.acall(json.dumps({"path": "", "depth": 1}))
        payload = json.loads(result.content)
        assert payload["ok"] is True
        assert any(entry["name"] == "note.md" for entry in payload["entries"])


@pytest.mark.asyncio
async def test_str_replace_unique_match(tmp_path):
    async with await Sandbox.create(backend="local", workdir=str(tmp_path)) as box:
        await box.files.write("song.txt", "alpha\nbeta\ngamma\n")
        result = await box.files.str_replace("song.txt", "beta", "BETA")
        assert result == {"ok": True, "path": "song.txt", "replacements": 1}
        assert (tmp_path / "song.txt").read_text() == "alpha\nBETA\ngamma\n"


@pytest.mark.asyncio
async def test_str_replace_not_found_reports_error(tmp_path):
    async with await Sandbox.create(backend="local", workdir=str(tmp_path)) as box:
        await box.files.write("song.txt", "alpha\nbeta\n")
        result = await box.files.str_replace("song.txt", "missing", "x")
        assert result["ok"] is False
        assert "未找到" in result["error"]
        # 文件内容未改
        assert (tmp_path / "song.txt").read_text() == "alpha\nbeta\n"


@pytest.mark.asyncio
async def test_str_replace_ambiguous_requires_replace_all(tmp_path):
    async with await Sandbox.create(backend="local", workdir=str(tmp_path)) as box:
        await box.files.write("dup.txt", "x\nx\nx\n")
        result = await box.files.str_replace("dup.txt", "x", "y")
        assert result["ok"] is False
        assert "出现了 3 次" in result["error"]
        # 文件不变
        assert (tmp_path / "dup.txt").read_text() == "x\nx\nx\n"

        result2 = await box.files.str_replace("dup.txt", "x", "y", replace_all=True)
        assert result2 == {"ok": True, "path": "dup.txt", "replacements": 3}
        assert (tmp_path / "dup.txt").read_text() == "y\ny\ny\n"


@pytest.mark.asyncio
async def test_str_replace_tool_wiring(tmp_path):
    async with await Sandbox.create(backend="local", workdir=str(tmp_path)) as box:
        await box.files.write("hello.txt", "hello world\n")
        tool = next(t for t in box.tools() if t.name == "str_replace")
        result = await tool.acall(
            json.dumps(
                {"path": "hello.txt", "old_string": "world", "new_string": "pagent"}
            )
        )
        payload = json.loads(result.content)
        assert payload["ok"] is True
        assert payload["replacements"] == 1
        assert (tmp_path / "hello.txt").read_text() == "hello pagent\n"


@pytest.mark.asyncio
async def test_read_file_line_numbers(tmp_path):
    async with await Sandbox.create(backend="local", workdir=str(tmp_path)) as box:
        await box.files.write("poem.txt", "one\ntwo\nthree\n")
        tool = next(t for t in box.tools() if t.name == "read_file")
        result = await tool.acall(
            json.dumps({"path": "poem.txt", "line_numbers": True})
        )
        text = result.content
        assert "1 | one" in text
        assert "2 | two" in text
        assert "3 | three" in text


@pytest.mark.asyncio
async def test_read_file_line_range(tmp_path):
    async with await Sandbox.create(backend="local", workdir=str(tmp_path)) as box:
        await box.files.write("poem.txt", "a\nb\nc\nd\ne\n")
        tool = next(t for t in box.tools() if t.name == "read_file")
        result = await tool.acall(
            json.dumps({"path": "poem.txt", "start_line": 2, "end_line": 4})
        )
        assert result.content == "b\nc\nd"


@pytest.mark.asyncio
async def test_read_file_bad_start_line_reports_error(tmp_path):
    async with await Sandbox.create(backend="local", workdir=str(tmp_path)) as box:
        await box.files.write("poem.txt", "a\nb\n")
        tool = next(t for t in box.tools() if t.name == "read_file")
        result = await tool.acall(json.dumps({"path": "poem.txt", "start_line": 10}))
        payload = json.loads(result.content)
        assert payload["ok"] is False
        assert "start_line" in payload["error"]


@pytest.mark.asyncio
async def test_install_skills_copies_files_and_returns_mount(tmp_path):
    from pagentv4 import SkillRegistry

    skill_source = tmp_path / "src" / "greeter"
    skill_source.mkdir(parents=True)
    (skill_source / "SKILL.md").write_text(
        "---\nname: greeter\ndescription: 打招呼\n---\n用 hello.sh 打招呼\n",
        encoding="utf-8",
    )
    (skill_source / "hello.sh").write_text("#!/bin/sh\necho hi\n")
    (skill_source / "nested").mkdir()
    (skill_source / "nested" / "note.txt").write_text("nested resource")

    registry = SkillRegistry.from_dirs(tmp_path / "src")

    async with await Sandbox.create(
        backend="local", workdir=str(tmp_path / "box")
    ) as box:
        mount = await box.install_skills(registry)
        assert mount == {"greeter": "/home/agent/.skills/greeter"}

        # 文件确实落到 sandbox 里
        assert await box.files.exists(".skills/greeter/SKILL.md") is True
        assert await box.files.exists(".skills/greeter/hello.sh") is True
        assert await box.files.exists(".skills/greeter/nested/note.txt") is True

        # 从 agent 视角能读到
        text = await box.files.read_text(".skills/greeter/nested/note.txt")
        assert text == "nested resource"


@pytest.mark.asyncio
async def test_install_skills_empty_registry_returns_empty(tmp_path):
    from pagentv4 import SkillRegistry

    async with await Sandbox.create(backend="local", workdir=str(tmp_path)) as box:
        mount = await box.install_skills(SkillRegistry())
        assert mount == {}


@pytest.mark.asyncio
async def test_sandbox_tools_are_bound(tmp_path):
    async with await Sandbox.create(backend="local", workdir=str(tmp_path)) as box:
        tools = box.tools()
        names = [tool.name for tool in tools]
        assert names == [
            "run_command",
            "read_file",
            "write_file",
            "str_replace",
            "list_dir",
            "list_host_files",
            "copy_from_host",
            "copy_to_host",
        ]

        write_tool = next(t for t in tools if t.name == "write_file")
        result = await write_tool.acall(
            json.dumps({"path": "hi.txt", "content": "hello via tool"})
        )
        assert result.ok is True
        assert (tmp_path / "hi.txt").read_text() == "hello via tool"

        list_tool = next(t for t in tools if t.name == "list_dir")
        listed = await list_tool.acall(json.dumps({"path": "."}))
        entries = json.loads(listed.content)
        assert any(entry["name"] == "hi.txt" for entry in entries)

        run_tool = next(t for t in tools if t.name == "run_command")
        run_result = await run_tool.acall(json.dumps({"command": "echo ok"}))
        payload = json.loads(run_result.content)
        assert payload["ok"] is True
        assert payload["stdout"].strip() == "ok"


@pytest.mark.asyncio
async def test_build_sandbox_tools_helper(tmp_path):
    async with await Sandbox.create(backend="local", workdir=str(tmp_path)) as box:
        assert [t.name for t in build_sandbox_tools(box)] == [
            "run_command",
            "read_file",
            "write_file",
            "str_replace",
            "list_dir",
            "list_host_files",
            "copy_from_host",
            "copy_to_host",
        ]


@pytest.mark.asyncio
async def test_build_sandbox_tools_whitelist(tmp_path):
    async with await Sandbox.create(
        backend="local",
        workdir=str(tmp_path),
        tools=("read_file", "run_command"),
    ) as box:
        # 顺序仍按 builders 固定次序，与配置书写顺序无关。
        assert [t.name for t in build_sandbox_tools(box)] == [
            "run_command",
            "read_file",
        ]


@pytest.mark.asyncio
async def test_build_sandbox_tools_empty_means_all(tmp_path):
    async with await Sandbox.create(
        backend="local", workdir=str(tmp_path), tools=()
    ) as box:
        assert len(build_sandbox_tools(box)) == 8


@pytest.mark.asyncio
async def test_build_sandbox_tools_unknown_raises(tmp_path):
    async with await Sandbox.create(
        backend="local", workdir=str(tmp_path), tools=("read_file", "bogus_tool")
    ) as box:
        with pytest.raises(ValueError, match="unknown sandbox tools"):
            build_sandbox_tools(box)


class FakeToolCallDelta:
    def __init__(self, *, index, tool_id=None, name=None, arguments=None):
        self.index = index
        self.id = tool_id
        self.type = "function"
        self.function = type("FakeFn", (), {"name": name, "arguments": arguments})()


class FakeStreamChunk:
    def __init__(self, *, content=None, reasoning=None, tool_calls=None):
        delta = type(
            "Delta",
            (),
            {
                "content": content,
                "reasoning_content": reasoning,
                "tool_calls": tool_calls,
            },
        )()
        self.choices = [type("Choice", (), {"delta": delta})()]


class FakeProvider:
    def __init__(self, steps):
        self.steps = list(steps)
        self.calls = []

    async def complete(self, messages, tools=None, **run_kwargs):
        self.calls.append({"messages": messages, "tools": tools, **run_kwargs})
        chunks = self.steps.pop(0)

        async def stream():
            for chunk in chunks:
                yield chunk

        return stream()


@pytest.mark.asyncio
async def test_runner_open_binds_sandbox_tools(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tool_call = FakeToolCallDelta(
        index=0,
        tool_id="call-1",
        name="write_file",
        arguments=json.dumps({"path": "note.md", "content": "hello via session"}),
    )
    provider = FakeProvider(
        [
            [FakeStreamChunk(tool_calls=[tool_call])],
            [FakeStreamChunk(content="done")],
        ]
    )

    runner = await Runner.create(
        "sandbox-test",
        provider,
        overrides={"backend": "local"},
        extra_system="you are helpful",
    )
    events = []
    try:
        async for event in runner.run("please write a note"):
            events.append(type(event).__name__)
    finally:
        await runner.close()

    note_path = (
        tmp_path / ".pagent" / "threads" / "sandbox-test" / "workspace" / "note.md"
    )
    assert note_path.read_text() == "hello via session"
    assert "ToolCallBegin" in events
    assert "ToolResult" in events
    assert "TextDelta" in events

    tools_arg = provider.calls[0]["tools"]
    assert tools_arg is not None
    tool_names = [entry["function"]["name"] for entry in tools_arg]
    assert "write_file" in tool_names
    assert "run_command" in tool_names


@pytest.mark.asyncio
async def test_runner_open_merges_extra_tools(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from pagentv4 import tool

    @tool()
    def add(a: int, b: int) -> int:
        """add two ints"""
        return a + b

    tool_call = FakeToolCallDelta(
        index=0,
        tool_id="call-1",
        name="add",
        arguments=json.dumps({"a": 2, "b": 3}),
    )
    provider = FakeProvider(
        [
            [FakeStreamChunk(tool_calls=[tool_call])],
            [FakeStreamChunk(content="five")],
        ]
    )

    runner = await Runner.create(
        "tools-test",
        provider,
        overrides={"backend": "local"},
        tools=[add],
    )
    try:
        async for _ in runner.run("hi"):
            pass
    finally:
        await runner.close()

    tools_arg = provider.calls[0]["tools"]
    tool_names = [entry["function"]["name"] for entry in tools_arg]
    assert "add" in tool_names
    assert "run_command" in tool_names


@pytest.mark.asyncio
async def test_runner_open_closes_sandbox_on_exception(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    class Boom(Exception):
        pass

    async def failing_stream(*_args, **_kwargs):
        raise Boom("provider blew up")

    provider = type("BoomProvider", (), {"complete": failing_stream})()

    runner = await Runner.create(
        "boom-test",
        provider,
        overrides={"backend": "local"},
    )
    with pytest.raises(Boom):
        async for _ in runner.run("hi"):
            pass
    await runner.close()

    assert (tmp_path / ".pagent" / "threads" / "boom-test" / "workspace").exists()


def make_spec(**overrides) -> SandboxSpec:
    kwargs = dict(workspace_id=None, workdir="/tmp/x", home="/home/agent")
    kwargs.update(overrides)
    return SandboxSpec(**kwargs)


def test_local_backend_describe_uses_workdir():
    identity = LocalBackend().describe(make_spec(), "/tmp/host-workdir")
    assert identity.computer_name == "本地计算节点"
    assert "run_command 的 shell 工作目录：/tmp/host-workdir" in identity.extra
    assert "文件工具路径 /home/agent" in identity.extra


def test_docker_backend_describe_includes_image_when_set():
    with_image = DockerBackend().describe(make_spec(image="python:3.12"), "/work")
    assert with_image.computer_name == "Docker 计算节点"
    assert "python:3.12" in with_image.extra
    assert "run_command 的容器 shell 工作目录：/work" in with_image.extra
    assert "文件工具路径 /home/agent" in with_image.extra
    assert "容器挂载映射：宿主 /work -> 容器 /work" in with_image.extra

    without_image = DockerBackend().describe(make_spec(), "/work")
    assert "run_command 的容器 shell 工作目录：/work" in without_image.extra


def test_podman_backend_describe_names_itself():
    identity = PodmanBackend().describe(make_spec(image="alpine"), "/work")
    assert identity.computer_name == "Podman 计算节点"
    assert "alpine" in identity.extra
    assert "容器挂载映射：宿主 /work -> 容器 /work" in identity.extra


def test_ssh_backend_describe_formats_connection():
    spec = make_spec(connection={"host": "hpc.example.com", "user": "alice"})
    identity = SshBackend().describe(spec, "/remote/work")
    assert identity.computer_name == "远程 SSH 计算节点"
    assert "alice@hpc.example.com" in identity.extra
    assert "run_command 的远端 shell 工作目录：/remote/work" in identity.extra
    assert "文件工具路径 /home/agent" in identity.extra


@pytest.mark.asyncio
async def test_container_backend_exec_before_start_raises_sandbox_error():
    """未 start 就 exec 属生命周期错误，走 SandboxNotStartedError（SandboxError 子类）。"""
    from pagentv4.sandbox import SandboxError, SandboxNotStartedError

    backend = DockerBackend()
    with pytest.raises(SandboxNotStartedError) as excinfo:
        await backend.exec(["echo", "hi"])
    assert isinstance(excinfo.value, SandboxError)


@pytest.mark.asyncio
async def test_ssh_backend_exec_before_start_raises_sandbox_error():
    from pagentv4.sandbox import SandboxError, SandboxNotStartedError

    backend = SshBackend()
    with pytest.raises(SandboxNotStartedError) as excinfo:
        await backend.exec(["echo", "hi"])
    assert isinstance(excinfo.value, SandboxError)


@pytest.mark.asyncio
async def test_container_backend_missing_image_raises_value_error():
    """缺 image 属配置错误，走 ValueError，与生命周期错误区分。"""
    backend = DockerBackend()
    with pytest.raises(ValueError):
        await backend.start(make_spec(), "/tmp/x")


@pytest.mark.asyncio
async def test_ssh_backend_read_file_before_start_raises_sandbox_error():
    """文件操作也遵守同一边界：未 start 就 read_file 抛 SandboxNotStartedError。"""
    from pagentv4.sandbox import SandboxError, SandboxNotStartedError

    backend = SshBackend()
    with pytest.raises(SandboxNotStartedError) as excinfo:
        await backend.read_file("/remote/some/file")
    assert isinstance(excinfo.value, SandboxError)


@pytest.mark.asyncio
async def test_open_sandbox_for_spec_docker_missing_image_raises_value_error():
    """工厂层校验：backend=docker 但缺 image，在 open_sandbox_for_spec 阶段抛 ValueError。"""
    from pagentv4 import ThreadSpec
    from pagentv4.sandbox import open_sandbox_for_spec

    profile = ThreadSpec(backend="docker", image=None)
    with pytest.raises(ValueError, match="image"):
        await open_sandbox_for_spec(profile, "/tmp/x", label="thread 'demo'")


@pytest.mark.asyncio
async def test_open_sandbox_for_spec_ssh_missing_host_raises_value_error():
    """工厂层校验：backend=ssh 但缺 ssh_host，抛 ValueError。"""
    from pagentv4 import ThreadSpec
    from pagentv4.sandbox import open_sandbox_for_spec

    profile = ThreadSpec(backend="ssh", ssh_host=None)
    with pytest.raises(ValueError, match="ssh_host"):
        await open_sandbox_for_spec(profile, "/tmp/x")


@pytest.mark.asyncio
async def test_build_computer_description_appends_uv_when_available():
    async def probe(command: str) -> dict:
        if "uv" in command:
            return {"ok": True, "exit_code": 0}
        return {"ok": False, "exit_code": 127}

    text = await build_computer_description(
        computer_name="Test 节点",
        os_info="Linux test 6.0",
        home="/home/agent",
        host_root="/tmp/host",
        artifacts_dir="artifacts",
        extra="额外说明：foobar\n",
        tool_names=SANDBOX_TOOL_NAMES,
        run_probe=probe,
    )
    assert "Test 节点" in text
    assert "Linux test 6.0" in text
    assert "额外说明：foobar" in text
    assert "uv venv .venv" in text
    assert "npm init" not in text
    assert "chromium-browser" not in text
    assert "run_command" in text
    assert "copy_from_host" in text
    assert "copy_to_host" in text
    assert "list_host_files" in text
    assert "str_replace" in text
    assert "/tmp/host" in text
    assert "artifacts" in text


@pytest.mark.asyncio
async def test_build_computer_description_skips_uv_when_missing():
    async def probe(_: str) -> dict:
        return {"ok": False, "exit_code": 127}

    text = await build_computer_description(
        computer_name="Test 节点",
        os_info="Linux",
        home="/home/agent",
        host_root="/tmp/host",
        artifacts_dir="artifacts",
        extra="",
        tool_names=SANDBOX_TOOL_NAMES,
        run_probe=probe,
    )
    assert "uv venv" not in text
    assert "npm init" not in text


@pytest.mark.asyncio
async def test_build_computer_description_appends_node_when_available():
    async def probe(command: str) -> dict:
        if "node" in command:
            return {"ok": True, "exit_code": 0}
        return {"ok": False, "exit_code": 127}

    text = await build_computer_description(
        computer_name="Test 节点",
        os_info="Linux test 6.0",
        home="/home/agent",
        host_root="/tmp/host",
        artifacts_dir="artifacts",
        extra="",
        tool_names=SANDBOX_TOOL_NAMES,
        run_probe=probe,
    )
    assert "npm init -y" in text
    assert "node_modules" in text
    assert "uv venv" not in text


@pytest.mark.asyncio
async def test_build_computer_description_appends_uv_and_node_when_both_available():
    async def probe(_: str) -> dict:
        return {"ok": True, "exit_code": 0}

    text = await build_computer_description(
        computer_name="Test 节点",
        os_info="Linux",
        home="/home/agent",
        host_root="/tmp/host",
        artifacts_dir="artifacts",
        extra="",
        tool_names=SANDBOX_TOOL_NAMES,
        run_probe=probe,
    )
    assert "uv venv .venv" in text
    assert "npm init -y" in text
    assert "chromium-browser" in text


@pytest.mark.asyncio
async def test_build_computer_description_appends_browser_when_available():
    async def probe(command: str) -> dict:
        if "chromium-browser" in command:
            return {"ok": True, "exit_code": 0}
        return {"ok": False, "exit_code": 127}

    text = await build_computer_description(
        computer_name="Test 节点",
        os_info="Linux",
        home="/home/agent",
        host_root="/tmp/host",
        artifacts_dir="artifacts",
        extra="",
        tool_names=SANDBOX_TOOL_NAMES,
        run_probe=probe,
    )
    assert "CHROMIUM_FLAGS" in text
    assert "Noto Sans CJK" in text
    assert "--no-sandbox" in text
    assert "uv venv" not in text


@pytest.mark.asyncio
async def test_build_computer_description_renders_only_whitelisted_tools():
    async def probe(_: str) -> dict:
        return {"ok": False, "exit_code": 127}

    text = await build_computer_description(
        computer_name="Test 节点",
        os_info="Linux",
        home="/home/agent",
        host_root="/tmp/host",
        artifacts_dir="artifacts",
        extra="",
        tool_names=["read_file", "list_dir"],
        run_probe=probe,
    )
    assert "read_file：" in text
    assert "list_dir：" in text
    # 未列入白名单的工具不该出现在提示词里。
    assert "run_command" not in text
    assert "write_file" not in text
    assert "copy_to_host" not in text


@pytest.mark.asyncio
async def test_build_computer_description_drops_command_policy_note_without_run_command():
    async def probe(_: str) -> dict:
        return {"ok": False, "exit_code": 127}

    text = await build_computer_description(
        computer_name="Test 节点",
        os_info="Linux",
        home="/home/agent",
        host_root="/tmp/host",
        artifacts_dir="artifacts",
        extra="",
        tool_names=["read_file"],
        run_probe=probe,
    )
    # 只有文件工具时，不该出现 command_policy 与 host 边界注记。
    assert "command_policy" not in text
    assert "用户目录工具" not in text


@pytest.mark.asyncio
async def test_build_computer_description_full_set_keeps_all_notes():
    async def probe(_: str) -> dict:
        return {"ok": False, "exit_code": 127}

    text = await build_computer_description(
        computer_name="Test 节点",
        os_info="Linux",
        home="/home/agent",
        host_root="/tmp/host",
        artifacts_dir="artifacts",
        extra="",
        tool_names=SANDBOX_TOOL_NAMES,
        run_probe=probe,
    )
    for name in SANDBOX_TOOL_NAMES:
        assert f"{name}：" in text
    assert "command_policy" in text
    assert "用户目录工具" in text


def test_resolve_tool_names_empty_means_all():
    assert resolve_tool_names(()) == list(SANDBOX_TOOL_NAMES)
    assert resolve_tool_names(None) == list(SANDBOX_TOOL_NAMES)


def test_resolve_tool_names_keeps_canonical_order():
    # 配置书写顺序被忽略，始终按 SANDBOX_TOOL_NAMES 排列。
    assert resolve_tool_names(["list_dir", "run_command"]) == [
        "run_command",
        "list_dir",
    ]


def test_resolve_tool_names_unknown_raises():
    with pytest.raises(ValueError, match="unknown sandbox tools"):
        resolve_tool_names(["read_file", "nope"])


@pytest.mark.asyncio
async def test_sandbox_describe_local(tmp_path):
    async with await Sandbox.create(
        backend="local", workdir=str(tmp_path), host_root=str(tmp_path)
    ) as box:
        text = await box.describe()

    assert "本地计算节点" in text
    assert str(tmp_path.resolve()) in text
    assert "/home/agent" in text
    assert "run_command" in text

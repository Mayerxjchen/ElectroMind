"""Thread / ThreadSpec 单测：目录布局 + 首次冻结 + TOML 配置行为。"""

from __future__ import annotations

import tomllib

import pytest

from pagentv4 import Thread, ThreadSpec
from pagentv4.conversation import SqliteConversationStore
from pagentv4.core.message import Message
from pagentv4.ithread import validate_thread_id
from pagentv4.runtime.thread import default_threads_root


def test_default_threads_root_is_user_home(monkeypatch, tmp_path):
    monkeypatch.delenv("PAGENT_HOME", raising=False)
    home = tmp_path / "home"
    cwd = tmp_path / "cwd"
    home.mkdir()
    cwd.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(cwd)
    assert default_threads_root() == home / ".pagent" / "threads"


@pytest.mark.parametrize("bad", ["", "-leading", "a/b", "a b", "x" * 129])
def test_validate_thread_id_rejects_bad(bad):
    with pytest.raises(ValueError):
        validate_thread_id(bad)


def test_thread_open_creates_spec_and_workspace(tmp_path):
    thread = Thread.open(
        "demo",
        root=tmp_path,
        overrides={"backend": "podman", "image": "foo:latest"},
    )
    assert thread.created is True
    assert thread.ignored_overrides == ()
    assert thread.root == tmp_path / "demo"
    assert (tmp_path / "demo" / "thread.toml").exists()
    assert (tmp_path / "demo" / "workspace").is_dir()

    payload = tomllib.loads((tmp_path / "demo" / "thread.toml").read_text())
    assert payload["sandbox"]["backend"] == "podman"
    assert payload["sandbox"]["image"] == "foo:latest"
    assert payload["conversation"]["backend"] == "jsonl"
    assert payload["conversation"]["messages_id"] == "messages"


def test_thread_open_resume_ignores_overrides(tmp_path):
    Thread.open(
        "demo",
        root=tmp_path,
        overrides={"backend": "podman", "image": "foo:latest"},
    )
    second = Thread.open(
        "demo",
        root=tmp_path,
        overrides={"backend": "local", "image": "bar:2"},
    )
    assert second.created is False
    assert second.spec.backend == "podman"
    assert second.spec.image == "foo:latest"
    assert set(second.ignored_overrides) == {"backend", "image"}


def test_thread_open_resume_fills_missing_project_path(tmp_path):
    Thread.open("demo", root=tmp_path, overrides={"backend": "local"})
    project = tmp_path / "project"

    second = Thread.open(
        "demo",
        root=tmp_path,
        overrides={"project_path": str(project)},
    )

    assert second.created is False
    assert second.ignored_overrides == ()
    assert second.spec.project_path == str(project)
    payload = tomllib.loads((tmp_path / "demo" / "thread.toml").read_text())
    assert payload["project"]["path"] == str(project)


def test_thread_open_resume_matching_overrides_no_warning(tmp_path):
    Thread.open(
        "demo",
        root=tmp_path,
        overrides={"backend": "podman", "image": "foo:latest"},
    )
    second = Thread.open(
        "demo",
        root=tmp_path,
        overrides={"backend": "podman", "image": "foo:latest"},
    )
    assert second.ignored_overrides == ()


def test_threads_are_isolated_from_each_other(tmp_path):
    first = Thread.open("alpha", root=tmp_path, overrides={"backend": "podman"})
    second = Thread.open("beta", root=tmp_path, overrides={"backend": "local"})

    (first.workspace_path / "a.txt").write_text("from alpha")
    (second.workspace_path / "b.txt").write_text("from beta")

    assert first.root != second.root
    assert first.spec.backend == "podman"
    assert second.spec.backend == "local"
    assert (first.workspace_path / "a.txt").exists()
    assert not (first.workspace_path / "b.txt").exists()
    assert (second.workspace_path / "b.txt").exists()
    assert not (second.workspace_path / "a.txt").exists()


def test_thread_spec_from_dict_carries_unknown_into_extra():
    spec = ThreadSpec.from_dict(
        {
            "sandbox": {"backend": "ssh"},
            "ssh": {"host": "foo"},
            "future_field": "x",
        }
    )
    assert spec.backend == "ssh"
    assert spec.ssh_host == "foo"
    assert spec.extra == {"future_field": "x"}


def test_thread_open_store_and_load_messages(tmp_path):
    thread = Thread.open("demo", root=tmp_path)
    store = thread.open_store()

    messages = thread.load_messages()
    assert messages.data == []

    messages += Message.system("sys")
    messages += Message.user("hi", turn_id=1)
    store.save(thread.messages_conversation_id, messages)

    reloaded = thread.load_messages()
    assert [message.role for message in reloaded.data] == ["system", "user"]
    assert reloaded.data[-1].content.text == "hi"
    assert thread.messages_storage_path.name == "messages.jsonl"


def test_thread_open_store_sqlite(tmp_path):
    thread = Thread.open(
        "demo",
        root=tmp_path,
        overrides={
            "conversation_backend": "sqlite",
            "conversation_db_path": "messages.sqlite",
        },
    )
    store = thread.open_store()
    try:
        assert isinstance(store, SqliteConversationStore)
        assert thread.messages_storage_path.name == "messages.sqlite"
    finally:
        store.close()


@pytest.mark.asyncio
async def test_thread_open_sandbox_local(tmp_path):
    thread = Thread.open("demo", root=tmp_path, overrides={"backend": "local"})

    sandbox = await thread.open_sandbox()
    try:
        assert sandbox.workdir == str(thread.workspace_path)
    finally:
        await sandbox.close()

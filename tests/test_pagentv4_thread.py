"""Thread / ThreadSpec 单测：目录布局 + 首次冻结 + reset 行为。"""

from __future__ import annotations

import json

import pytest

from pagentv4 import Thread, ThreadSpec
from pagentv4.runtime.thread import default_threads_root, validate_thread_id


def test_default_threads_root_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("PAGENT_THREADS_DIR", str(tmp_path))
    assert default_threads_root() == tmp_path


def test_default_threads_root_falls_back_to_cwd(monkeypatch, tmp_path):
    monkeypatch.delenv("PAGENT_THREADS_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert default_threads_root() == tmp_path / ".pagent" / "threads"


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
    assert (tmp_path / "demo" / "spec.json").exists()
    assert (tmp_path / "demo" / "workspace").is_dir()

    payload = json.loads((tmp_path / "demo" / "spec.json").read_text())
    assert payload["backend"] == "podman"
    assert payload["image"] == "foo:latest"


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
        {"backend": "ssh", "ssh_host": "foo", "future_field": "x"}
    )
    assert spec.backend == "ssh"
    assert spec.ssh_host == "foo"
    assert spec.extra == {"future_field": "x"}

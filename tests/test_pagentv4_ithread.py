"""IThread Protocol、ThreadSpec、validate_thread_id 单测。"""

import pytest

from pagentv4.ithread import IThread, ThreadSpec, validate_thread_id
from pagentv4.runtime.thread import Thread


def test_thread_satisfies_ithread_protocol():
    """Thread 实例满足 IThread Protocol。"""
    thread = Thread.open("proto-check", root="/tmp/ithread-test-proto")
    assert isinstance(thread, IThread)


def test_validate_thread_id_accepts_valid():
    validate_thread_id("abc")
    validate_thread_id("a-b_c.123")


@pytest.mark.parametrize("bad", ["", "-leading", "a/b", "a b", "x" * 129])
def test_validate_thread_id_rejects_bad(bad):
    with pytest.raises(ValueError):
        validate_thread_id(bad)


def test_thread_spec_defaults():
    spec = ThreadSpec()
    assert spec.conversation_backend == "jsonl"
    assert spec.backend == "local"
    assert spec.model == "deepseek-v4-flash"
    assert spec.extra == {}


def test_thread_spec_from_dict_flattens_sections():
    spec = ThreadSpec.from_dict(
        {
            "sandbox": {"backend": "ssh"},
            "ssh": {"host": "myhost"},
            "agent": {"model": "gpt-5"},
        }
    )
    assert spec.backend == "ssh"
    assert spec.ssh_host == "myhost"
    assert spec.model == "gpt-5"


def test_thread_spec_from_dict_unknown_fields_go_to_extra():
    spec = ThreadSpec.from_dict({"sandbox": {"backend": "local"}, "future_field": "x"})
    assert spec.extra == {"future_field": "x"}


def test_thread_spec_to_dict_roundtrip():
    original = ThreadSpec(
        backend="docker",
        image="test:1",
        model="gpt-5",
        project_path="/tmp/demo-project",
    )
    restored = ThreadSpec.from_dict(original.to_dict())
    assert restored.backend == original.backend
    assert restored.image == original.image
    assert restored.model == original.model
    assert restored.project_path == original.project_path


def test_thread_spec_field_names():
    names = ThreadSpec.field_names()
    assert "backend" in names
    assert "project_path" in names
    assert "model" in names
    assert "extra" in names


def test_thread_workspace_path_uses_project_path(tmp_path):
    project = tmp_path / "project"
    thread = Thread.open(
        "project-binding",
        root=tmp_path / "threads",
        overrides={"project_path": str(project)},
    )
    assert thread.workspace_path == project.resolve()

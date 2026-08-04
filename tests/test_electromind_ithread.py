"""IThread Protocol、ThreadSpec、validate_thread_id 单测。"""

import pytest

from electromind.ithread import IThread, ThreadSpec, validate_thread_id
from electromind.runtime.thread import Thread


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


def test_thread_spec_sandbox_tools_toml_roundtrip():
    import tomllib

    from electromind.ithread.local import dump_thread_toml

    original = ThreadSpec(
        backend="local",
        sandbox_tools=("run_command", "read_file"),
    )
    text = dump_thread_toml(original.to_dict())
    restored = ThreadSpec.from_dict(tomllib.loads(text))
    assert list(restored.sandbox_tools) == ["run_command", "read_file"]


def test_thread_spec_empty_sandbox_tools_omitted_from_toml():
    from electromind.ithread.local import dump_thread_toml

    text = dump_thread_toml(ThreadSpec(backend="local").to_dict())
    assert "tools" not in text


def test_thread_spec_sub_config_toml_roundtrip():
    import tomllib

    from electromind.ithread import SubAgentSpec
    from electromind.ithread.local import dump_thread_toml

    original = ThreadSpec(
        backend="local",
        subs={
            "researcher": SubAgentSpec(
                system="你是研究员", model="deepseek-v4", backend="none", max_turns=5
            ),
            "coder": SubAgentSpec(
                sandbox_tools=("run_command", "read_file"), workspace="coder"
            ),
        },
    )
    text = dump_thread_toml(original.to_dict())
    assert "[sub.researcher]" in text
    assert "[sub.coder]" in text

    restored = ThreadSpec.from_dict(tomllib.loads(text))
    assert sorted(restored.subs) == ["coder", "researcher"]
    assert restored.subs["researcher"].system == "你是研究员"
    assert restored.subs["researcher"].backend == "none"
    assert restored.subs["researcher"].max_turns == 5
    assert restored.subs["coder"].sandbox_tools == ("run_command", "read_file")
    assert restored.subs["coder"].workspace == "coder"


def test_thread_spec_no_subs_omits_sub_section():
    from electromind.ithread.local import dump_thread_toml

    text = dump_thread_toml(ThreadSpec(backend="local").to_dict())
    assert "[sub." not in text


def test_thread_spec_subs_normalized_from_plain_dict():
    from electromind.ithread import SubAgentSpec

    spec = ThreadSpec(subs={"helper": {"system": "hi", "max_turns": 3}})
    assert isinstance(spec.subs["helper"], SubAgentSpec)
    assert spec.subs["helper"].max_turns == 3


def test_thread_spec_field_names():
    names = ThreadSpec.field_names()
    assert "backend" in names
    assert "project_path" in names
    assert "model" in names
    assert "extra" in names


def test_thread_project_path_is_separate_from_workspace(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    thread = Thread.open(
        "project-binding",
        root=tmp_path / "threads",
        overrides={"project_path": str(project)},
    )
    assert (
        thread.workspace_path
        == (tmp_path / "threads" / "project-binding" / "workspaces" / "main").resolve()
    )
    assert thread.project_path == project.resolve()

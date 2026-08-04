import os

import pytest

from app.config import (
    BUNDLED_CONFIG,
    ReplConfig,
    build_parser,
    config_from_args,
    ensure_home_config,
    find_user_config,
    load_config,
    load_config_file,
    merge_config,
    parse_repl_config,
    refresh_provider_from_disk,
)
from electromind.paths import activate_home, default_electromind_home
from electromind.sandbox.tools import SANDBOX_TOOL_NAMES


def test_thread_overrides_includes_container_ttl():
    config = ReplConfig(backend="docker", image="demo:latest", container_ttl=300)
    assert config.thread_overrides()["container_ttl_seconds"] == 300


def test_thread_overrides_container_ttl_zero_means_infinity():
    config = ReplConfig(backend="docker", image="demo:latest", container_ttl=0)
    assert config.thread_overrides()["container_ttl_seconds"] is None


def test_thread_overrides_includes_command_policy():
    config = ReplConfig(backend="local", command_policy="workdir")
    assert config.thread_overrides()["command_policy"] == "workdir"


def test_thread_overrides_includes_sandbox_tools():
    config = ReplConfig(sandbox_tools=("run_command", "read_file"))
    assert config.thread_overrides()["sandbox_tools"] == ("run_command", "read_file")


def test_thread_overrides_omits_sandbox_tools_when_unset():
    config = ReplConfig(backend="local")
    assert "sandbox_tools" not in config.thread_overrides()


def test_parse_repl_config_sandbox_tools():
    config = parse_repl_config({"sandbox": {"tools": ["run_command", "read_file", ""]}})
    # 空串被过滤，其余保序。
    assert config.sandbox_tools == ("run_command", "read_file")


def test_parse_repl_config_sandbox_tools_rejects_non_list():
    with pytest.raises(ValueError, match="sandbox.tools"):
        parse_repl_config({"sandbox": {"tools": "run_command"}})


def test_thread_overrides_from_config():
    config = ReplConfig(
        backend="ssh",
        ssh_host="dev-host",
        ssh_config="~/.ssh/config",
        ssh_workdir="~/electromind",
        model="deepseek-v4-flash",
    )
    assert config.thread_overrides() == {
        "backend": "ssh",
        "ssh_host": "dev-host",
        "ssh_config": "~/.ssh/config",
        "ssh_workdir": "~/electromind",
        "model": "deepseek-v4-flash",
        # project_path 留空 → 冻结成启动时的 cwd 绝对路径（thread.toml 写具体值）。
        "project_path": os.path.abspath(os.getcwd()),
        # SSOT：harness 工具白名单与 skills 目录冻结进 thread.toml。
        "agent_tools": ("web_search", "fetch_url"),
        "skills": config.resolved_skill_dirs(),
    }


def test_parse_and_freeze_subagents():
    config = parse_repl_config(
        {
            "agent": {"tools": ["delegate_to_subagent"]},
            "sub": {
                "coder": {
                    "system": "你是程序员",
                    "max_turns": 24,
                    "workspace": "coder",
                },
                "researcher": {"system": "调研员", "backend": "none"},
            },
        }
    )
    assert config.agent_tools == ("delegate_to_subagent",)
    assert sorted(config.subs) == ["coder", "researcher"]
    assert config.subs["coder"].workspace == "coder"
    assert config.subs["researcher"].backend == "none"
    overrides = config.thread_overrides()
    assert overrides["agent_tools"] == ("delegate_to_subagent",)
    assert overrides["subs"]["coder"].system == "你是程序员"
    assert "subs" not in ReplConfig().thread_overrides()


def test_resolved_api_key_prefers_config(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "from-env")
    config = ReplConfig(api_key="from-toml")
    assert config.resolved_api_key() == "from-toml"


def test_resolved_api_key_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "from-env")
    config = ReplConfig()
    assert config.resolved_api_key() == "from-env"


def test_refresh_provider_from_disk_picks_up_new_key(tmp_path, monkeypatch):
    home = tmp_path / "home" / ".electromind"
    home.mkdir(parents=True)
    monkeypatch.setenv("ELECTROMIND_HOME", str(home))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    stale = ReplConfig()
    assert stale.resolved_api_key() is None
    (home / "config.toml").write_text(
        '[provider]\napi_key = "sk-after-setup"\nmodel = "deepseek-v4-flash"\n',
        encoding="utf-8",
    )
    refreshed = refresh_provider_from_disk(stale)
    assert refreshed.resolved_api_key() == "sk-after-setup"
    assert refreshed.resolved_model() == "deepseek-v4-flash"


def test_resolved_max_turns_default():
    assert ReplConfig().resolved_max_turns() == 24


def test_config_from_file(tmp_path, monkeypatch):
    # 隔离真实 ~/.electromind，避免本机用户配置污染默认值断言。
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    parser = build_parser()
    config = config_from_args(parser.parse_args([]))
    assert config.thread_id is None
    assert config.resolved_model() == "deepseek-v4-flash"
    assert config.backend == "local"
    assert config.image == "electromind:latest"
    assert config.container_ttl == 300
    assert config.ssh_host == "machine_root"
    assert config.command_policy == "workdir"
    assert config.resolved_max_turns() == 24
    assert config.ssh_config == "~/.ssh/config"
    assert config.ssh_workdir == "~/electromind"


def test_thread_id_from_cli_only(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    parser = build_parser()
    config = config_from_args(parser.parse_args(["--thread-id", "demo"]))
    assert config.thread_id == "demo"
    assert config.resolved_model() == "deepseek-v4-flash"


def test_backend_from_cli_overrides_project_config(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text(
        '[sandbox]\nbackend = "local"\n',
        encoding="utf-8",
    )
    parser = build_parser()
    config = config_from_args(parser.parse_args(["--backend", "ssh"]))
    assert config.backend == "ssh"


def test_runtime_modes_from_cli_override_project_config(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text(
        '[permission]\nmode = "prompt"\n\n[sandbox.ssh]\nhost = "old"\n',
        encoding="utf-8",
    )
    parser = build_parser()
    config = config_from_args(
        parser.parse_args(
            [
                "--permission-mode",
                "auto",
                "--ssh-host",
                "gpu-dev",
                "--ssh-config",
                "/tmp/ssh_config",
            ]
        )
    )
    assert config.permission_auto()
    assert config.ssh_host == "gpu-dev"
    assert config.ssh_config == "/tmp/ssh_config"


def test_parse_repl_config():
    data = {
        "runner": {"max_turns": 16},
        "provider": {
            "model": "deepseek-v4-flash",
            "api_key": "sk-test",
            "base_url": "https://api.example.com",
        },
        "sandbox": {
            "backend": "local",
            "container": {"image": ""},
            "ssh": {
                "host": "dev",
                "config_path": "/tmp/ssh_config",
                "workdir": "/tmp/agent",
            },
        },
        "skills": {"roots": ["./skills", "~/.agents/skills"]},
    }
    config = parse_repl_config(data)
    assert config.model == "deepseek-v4-flash"
    assert config.api_key == "sk-test"
    assert config.provider_base_url == "https://api.example.com"
    assert config.max_turns == 16
    assert config.backend == "local"
    assert config.image is None
    assert config.ssh_config == "/tmp/ssh_config"
    assert config.ssh_host == "dev"
    assert config.ssh_workdir == "/tmp/agent"
    assert config.skill_roots == ("./skills", "~/.agents/skills")


def test_parse_repl_config_nested_sandbox_blocks():
    data = {
        "sandbox": {
            "backend": "container",
            "command_policy": "workdir",
            "container": {"image": "electromind:latest", "container_ttl": 300},
            "ssh": {"host": "gpu", "config_path": "/tmp/cfg", "workdir": "~/work"},
        },
    }
    config = parse_repl_config(data)
    assert config.backend == "container"
    assert config.command_policy == "workdir"
    assert config.image == "electromind:latest"
    assert config.container_ttl == 300
    assert config.ssh_host == "gpu"
    assert config.ssh_config == "/tmp/cfg"
    assert config.ssh_workdir == "~/work"


def test_parse_repl_config_bundled_default():
    config = load_config_file(BUNDLED_CONFIG)
    assert config.backend == "local"
    assert config.image == "electromind:latest"
    assert config.container_ttl == 300
    assert config.ssh_host == "machine_root"
    assert config.ssh_workdir == "~/electromind"


def test_bundled_default_parses_full_schema():
    # src/electromind/resources/default-config.toml 是包内唯一内置默认，
    # 锁定它能被解析器解析且不腐烂成死字段。
    config = load_config_file(BUNDLED_CONFIG)
    assert config.max_turns == 24
    assert config.model == "deepseek-v4-flash"
    assert config.backend == "local"
    assert config.command_policy == "workdir"
    assert config.image == "electromind:latest"
    assert config.container_ttl == 300
    assert config.ssh_host == "machine_root"
    assert config.ssh_config == "~/.ssh/config"
    assert config.ssh_workdir == "~/electromind"
    assert config.resolved_user_label() == "you"
    assert config.resolved_assistant_label() == "electromind"
    assert config.permission_mode == "prompt"
    assert config.resolved_runner_location() == "local"
    # tools 解除注释后应列全 8 个，与 SANDBOX_TOOL_NAMES 一致（防止漏项或写错名）。
    assert config.sandbox_tools == SANDBOX_TOOL_NAMES


def test_runner_location_default_is_local():
    assert ReplConfig().resolved_runner_location() == "local"


def test_runner_location_parses_local():
    config = parse_repl_config({"runner": {"location": "local"}})
    assert config.runner_location == "local"
    assert config.resolved_runner_location() == "local"


def test_runner_location_rejects_unknown():
    with pytest.raises(ValueError, match="runner.location: 非法值"):
        parse_repl_config({"runner": {"location": "moon"}})


def test_runner_location_cloud_not_implemented():
    with pytest.raises(NotImplementedError, match="cloud"):
        parse_repl_config({"runner": {"location": "cloud"}})


def test_parse_repl_config_labels():
    config = parse_repl_config(
        {"repl": {"user_label": "human", "assistant_label": "bot"}}
    )
    assert config.resolved_user_label() == "human"
    assert config.resolved_assistant_label() == "bot"


def test_bundled_config_default_labels():
    config = load_config_file(BUNDLED_CONFIG)
    assert config.resolved_user_label() == "you"
    assert config.resolved_assistant_label() == "electromind"
    assert not config.permission_auto()


def test_parse_repl_config_permission_auto():
    config = parse_repl_config({"permission": {"mode": "auto"}})
    assert config.permission_auto()
    assert config.resolved_permission_mode() == "auto"


def test_config_from_args_auto_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    parser = build_parser()
    config = config_from_args(parser.parse_args(["--auto"]))
    assert config.permission_auto()


def test_dev_flag_activates_project_home(tmp_path, monkeypatch):
    from electromind.paths import resolve_electromind_home

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    parser = build_parser()
    config_from_args(parser.parse_args(["--dev", str(tmp_path)]))
    assert resolve_electromind_home() == (tmp_path / ".electromind").resolve()


def test_no_dev_flag_uses_user_home(tmp_path, monkeypatch):
    from electromind.paths import resolve_electromind_home

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    parser = build_parser()
    config_from_args(parser.parse_args([]))
    assert resolve_electromind_home() == (home / ".electromind").resolve()


def test_resolved_skill_roots_default():
    assert ReplConfig().resolved_skill_roots() == ()


def test_resolved_skill_dirs_expands_electromind_home(tmp_path, monkeypatch):
    activate_home("dev", tmp_path)
    config = ReplConfig(
        skill_roots=("{electromind_home}/skills", "{home}/legacy", "./local")
    )
    home = str(default_electromind_home())
    assert config.resolved_skill_dirs() == (
        f"{home}/skills",
        f"{home}/legacy",
        "./local",
    )


def test_parse_repl_config_skills_roots_string():
    config = parse_repl_config({"skills": {"roots": "./skills"}})
    assert config.skill_roots == ("./skills",)


def test_merge_config():
    base = ReplConfig(model="a", max_turns=24)
    override = ReplConfig(model="b", max_turns=20)
    merged = merge_config(base, override)
    assert merged.model == "b"
    assert merged.max_turns == 20


def test_load_project_config(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    activate_home("dev", tmp_path)
    project_home = tmp_path / ".electromind"
    project_home.mkdir()
    (project_home / "config.toml").write_text(
        '[runner]\nmax_turns = 24\n\n[provider]\nmodel = "custom-model"\n',
        encoding="utf-8",
    )
    config = load_config(workdir=str(tmp_path))
    assert config.model == "custom-model"
    assert config.max_turns == 24


def test_project_local_path_parses():
    config = parse_repl_config({"project": {"local": {"path": "/work/repo"}}})
    assert config.project_path == "/work/repo"


def test_project_local_empty_path_is_none():
    config = parse_repl_config({"project": {"local": {"path": ""}}})
    assert config.project_path is None


def test_project_defaults_to_none_without_local():
    assert parse_repl_config({}).project_path is None


def test_flat_project_path_is_rejected():
    with pytest.raises(ValueError, match="project.local"):
        parse_repl_config({"project": {"path": "/work/repo"}})


def test_find_user_config(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    activate_home("prod")
    assert find_user_config(str(tmp_path)) is None
    user_dir = tmp_path / ".electromind"
    user_dir.mkdir()
    user_toml = user_dir / "config.toml"
    user_toml.write_text('[provider]\napi_key = "sk-user"\n', encoding="utf-8")
    assert find_user_config(str(tmp_path)) == user_toml


def test_dev_mode_materializes_missing_config(tmp_path, monkeypatch):
    """--dev 指向空目录时，从包内模板物化 ./.electromind/config.toml，只认这一个文件。"""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    project = tmp_path / "proj"
    project.mkdir()
    activate_home("dev", project)

    target = project / ".electromind" / "config.toml"
    assert not target.exists()

    config = load_config(workdir=str(project))
    assert target.is_file()  # 缺失即物化
    assert target.read_text(encoding="utf-8") == BUNDLED_CONFIG.read_text(
        encoding="utf-8"
    )  # 内容取自打包种子
    assert config.backend == "local"
    assert default_electromind_home() == target.parent


def test_ensure_home_config_keeps_existing(tmp_path, monkeypatch):
    """已有 home 配置时不覆盖，直接沿用。"""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    project = tmp_path / "proj"
    home = project / ".electromind"
    home.mkdir(parents=True)
    existing = home / "config.toml"
    existing.write_text('[provider]\nmodel = "kept-model"\n', encoding="utf-8")
    activate_home("dev", project)

    path = ensure_home_config(workdir=str(project))
    assert path == existing
    assert existing.read_text(encoding="utf-8") == '[provider]\nmodel = "kept-model"\n'


def test_project_home_does_not_read_user_home(tmp_path, monkeypatch):
    """开发模式只用项目 home，不混读 ~/.electromind。"""
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    monkeypatch.setenv("HOME", str(home))
    activate_home("dev", project)

    user_dir = home / ".electromind"
    user_dir.mkdir()
    (user_dir / "config.toml").write_text(
        '[provider]\napi_key = "sk-user"\nmodel = "user-model"\n',
        encoding="utf-8",
    )
    project_home = project / ".electromind"
    project_home.mkdir()
    (project_home / "config.toml").write_text(
        '[provider]\nmodel = "project-model"\n',
        encoding="utf-8",
    )

    config = load_config(workdir=str(project))
    assert config.api_key is None or config.api_key == ""
    assert config.model == "project-model"


def test_explicit_config_merges_active_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    activate_home("prod")
    user_dir = home / ".electromind"
    user_dir.mkdir()
    (user_dir / "config.toml").write_text(
        '[provider]\napi_key = "sk-user"\n',
        encoding="utf-8",
    )
    explicit = tmp_path / "custom.toml"
    explicit.write_text('[provider]\nmodel = "explicit-model"\n', encoding="utf-8")

    config = load_config(config_path=explicit, workdir=str(tmp_path))
    assert config.api_key == "sk-user"
    assert config.model == "explicit-model"

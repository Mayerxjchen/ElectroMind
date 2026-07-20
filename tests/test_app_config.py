import pytest

from app.config import (
    BUNDLED_CONFIG,
    ReplConfig,
    build_parser,
    config_from_args,
    find_user_config,
    load_config,
    load_config_file,
    merge_config,
    parse_repl_config,
    refresh_provider_from_disk,
)


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
        ssh_host="pagent",
        ssh_config="~/.ssh/config",
        ssh_workdir="~/pagent",
        model="deepseek-v4-flash",
    )
    assert config.thread_overrides() == {
        "backend": "ssh",
        "ssh_host": "pagent",
        "ssh_config": "~/.ssh/config",
        "ssh_workdir": "~/pagent",
        "model": "deepseek-v4-flash",
    }


def test_resolved_api_key_prefers_config(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "from-env")
    config = ReplConfig(api_key="from-toml")
    assert config.resolved_api_key() == "from-toml"


def test_resolved_api_key_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "from-env")
    config = ReplConfig()
    assert config.resolved_api_key() == "from-env"


def test_refresh_provider_from_disk_picks_up_new_key(tmp_path, monkeypatch):
    home = tmp_path / "home" / ".pagent"
    home.mkdir(parents=True)
    monkeypatch.setenv("PAGENT_HOME", str(home))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    stale = ReplConfig()
    assert stale.resolved_api_key() is None
    (home / "pagent.toml").write_text(
        '[provider]\napi_key = "sk-after-setup"\nmodel = "deepseek-v4-flash"\n',
        encoding="utf-8",
    )
    refreshed = refresh_provider_from_disk(stale)
    assert refreshed.resolved_api_key() == "sk-after-setup"
    assert refreshed.resolved_model() == "deepseek-v4-flash"


def test_resolved_max_turns_default():
    assert ReplConfig().resolved_max_turns() == 12


def test_config_from_file(tmp_path, monkeypatch):
    # 隔离真实 ~/.pagent，避免本机用户配置污染默认值断言。
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    parser = build_parser()
    config = config_from_args(parser.parse_args([]))
    assert config.thread_id is None
    assert config.resolved_model() == "deepseek-v4-flash"
    assert config.backend == "container"
    assert config.image == "pagent:latest"
    assert config.container_ttl == 300
    assert config.ssh_host == "machine_root"
    assert config.command_policy == "workdir"
    assert config.resolved_max_turns() == 12
    assert config.ssh_config == "~/.ssh/config"
    assert config.ssh_workdir == "~/pagent"


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
    (tmp_path / "pagent.toml").write_text(
        '[sandbox]\nbackend = "local"\n',
        encoding="utf-8",
    )
    parser = build_parser()
    config = config_from_args(parser.parse_args(["--backend", "ssh"]))
    assert config.backend == "ssh"


def test_runtime_modes_from_cli_override_project_config(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pagent.toml").write_text(
        '[permission]\nmode = "prompt"\n\n[ssh]\nhost = "old"\n',
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
        "max_turns": 16,
        "provider": {
            "model": "deepseek-v4-flash",
            "api_key": "sk-test",
            "base_url": "https://api.example.com",
        },
        "sandbox": {"backend": "local", "image": ""},
        "ssh": {
            "host": "dev",
            "config_path": "/tmp/ssh_config",
            "workdir": "/tmp/agent",
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


def test_parse_repl_config_labels():
    config = parse_repl_config(
        {"repl": {"user_label": "human", "assistant_label": "bot"}}
    )
    assert config.resolved_user_label() == "human"
    assert config.resolved_assistant_label() == "bot"


def test_bundled_config_default_labels():
    config = load_config_file(BUNDLED_CONFIG)
    assert config.resolved_user_label() == "you"
    assert config.resolved_assistant_label() == "pagent"
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


def test_resolved_skill_roots_default():
    assert ReplConfig().resolved_skill_roots() == ()


def test_parse_repl_config_skills_roots_string():
    config = parse_repl_config({"skills": {"roots": "./skills"}})
    assert config.skill_roots == ("./skills",)


def test_merge_config():
    base = ReplConfig(model="a", max_turns=12)
    override = ReplConfig(model="b", max_turns=20)
    merged = merge_config(base, override)
    assert merged.model == "b"
    assert merged.max_turns == 20


def test_load_project_config(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "pagent.toml").write_text(
        'max_turns = 8\n\n[provider]\nmodel = "custom-model"\n',
        encoding="utf-8",
    )
    config = load_config(workdir=str(tmp_path))
    assert config.model == "custom-model"
    assert config.max_turns == 8


def test_find_user_config(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    assert find_user_config(str(tmp_path)) is None
    user_dir = tmp_path / ".pagent"
    user_dir.mkdir()
    user_toml = user_dir / "pagent.toml"
    user_toml.write_text('[provider]\napi_key = "sk-user"\n', encoding="utf-8")
    assert find_user_config(str(tmp_path)) == user_toml


def test_project_home_does_not_read_user_home(tmp_path, monkeypatch):
    """有 ./.pagent 时只用项目 home，不混读 ~/.pagent。"""
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    monkeypatch.setenv("HOME", str(home))

    user_dir = home / ".pagent"
    user_dir.mkdir()
    (user_dir / "pagent.toml").write_text(
        '[provider]\napi_key = "sk-user"\nmodel = "user-model"\n',
        encoding="utf-8",
    )
    project_home = project / ".pagent"
    project_home.mkdir()
    (project_home / "pagent.toml").write_text(
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
    monkeypatch.chdir(tmp_path)
    user_dir = home / ".pagent"
    user_dir.mkdir()
    (user_dir / "pagent.toml").write_text(
        '[provider]\napi_key = "sk-user"\n',
        encoding="utf-8",
    )
    explicit = tmp_path / "custom.toml"
    explicit.write_text('[provider]\nmodel = "explicit-model"\n', encoding="utf-8")

    config = load_config(config_path=explicit, workdir=str(tmp_path))
    assert config.api_key == "sk-user"
    assert config.model == "explicit-model"

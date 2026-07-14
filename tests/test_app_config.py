from app.config import (
    BUNDLED_CONFIG,
    ReplConfig,
    build_parser,
    config_from_args,
    load_config,
    load_config_file,
    merge_config,
    parse_repl_config,
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


def test_thread_overrides_from_config():
    config = ReplConfig(
        backend="ssh",
        ssh_host="pagent",
        ssh_config="~/.ssh/config",
        ssh_workdir="~/agent",
        model="deepseek-v4-flash",
    )
    assert config.thread_overrides() == {
        "backend": "ssh",
        "ssh_host": "pagent",
        "ssh_config": "~/.ssh/config",
        "ssh_workdir": "~/agent",
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


def test_resolved_max_turns_default():
    assert ReplConfig().resolved_max_turns() == 12


def test_config_from_file(tmp_path, monkeypatch):
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
    assert config.ssh_workdir == "~/"


def test_thread_id_from_cli_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    parser = build_parser()
    config = config_from_args(parser.parse_args(["--thread-id", "demo"]))
    assert config.thread_id == "demo"
    assert config.resolved_model() == "deepseek-v4-flash"


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


def test_load_project_config(tmp_path):
    (tmp_path / "pagent.toml").write_text(
        'max_turns = 8\n\n[provider]\nmodel = "custom-model"\n',
        encoding="utf-8",
    )
    config = load_config(workdir=str(tmp_path))
    assert config.model == "custom-model"
    assert config.max_turns == 8

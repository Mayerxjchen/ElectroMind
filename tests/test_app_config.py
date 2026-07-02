from app.config import (
    ReplConfig,
    build_parser,
    config_from_args,
    load_config,
    merge_config,
    parse_repl_config,
)


def test_thread_overrides_from_config():
    config = ReplConfig(
        backend="docker",
        image="python:3.12-slim",
        model="deepseek-v4-flash",
        ssh_config="~/.ssh/config",
    )
    assert config.thread_overrides() == {
        "backend": "docker",
        "image": "python:3.12-slim",
        "model": "deepseek-v4-flash",
        "ssh_config": "~/.ssh/config",
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
    assert config.backend == "local"
    assert config.resolved_max_turns() == 12
    assert config.ssh_config == "~/.ssh/config"


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
        "ssh": {"config_path": "/tmp/ssh_config"},
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
    assert config.skill_roots == ("./skills", "~/.agents/skills")


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

from app.config import ReplConfig
from app.setup import (
    DEFAULT_MODEL,
    ProviderSetup,
    needs_api_key,
    remove_provider_field,
    toml_escape,
    upsert_provider_api_key,
    upsert_provider_field,
    write_user_api_key,
    write_user_provider,
)


def test_toml_escape():
    assert toml_escape('a"b\\c') == 'a\\"b\\\\c'


def test_upsert_replaces_existing_key():
    text = '[provider]\napi_key = "old"\nmodel = "m"\n'
    out = upsert_provider_api_key(text, "new")
    assert 'api_key = "new"' in out
    assert 'model = "m"' in out
    assert "old" not in out


def test_upsert_adds_under_provider():
    text = '[provider]\nmodel = "m"\n'
    out = upsert_provider_api_key(text, "sk-x")
    assert "[provider]" in out
    assert 'api_key = "sk-x"' in out


def test_upsert_appends_provider_section():
    text = "max_turns = 24\n"
    out = upsert_provider_api_key(text, "sk-x")
    assert out.startswith("max_turns = 24\n")
    assert "[provider]" in out
    assert 'api_key = "sk-x"' in out


def test_write_user_provider_full(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)

    path = write_user_provider(
        ProviderSetup(
            api_key="sk-test",
            model="my-model",
            base_url="https://example.com/v1",
        ),
        cwd=tmp_path,
    )
    assert path == home / ".pagent" / "pagent.toml"
    text = path.read_text(encoding="utf-8")
    assert 'api_key = "sk-test"' in text
    assert 'model = "my-model"' in text
    assert 'base_url = "https://example.com/v1"' in text


def test_write_user_provider_clears_base_url(tmp_path, monkeypatch):
    home = tmp_path / "home"
    cfg = home / ".pagent" / "pagent.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(
        '[provider]\napi_key = "old"\nbase_url = "https://old"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)

    write_user_provider(
        ProviderSetup(api_key="sk-new", model=DEFAULT_MODEL), cwd=tmp_path
    )
    text = cfg.read_text(encoding="utf-8")
    assert 'api_key = "sk-new"' in text
    assert "base_url" not in text


def test_write_user_api_key_creates_file(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)

    path = write_user_api_key("sk-test-key")
    text = path.read_text(encoding="utf-8")
    assert 'api_key = "sk-test-key"' in text
    assert f'model = "{DEFAULT_MODEL}"' in text


def test_remove_provider_field():
    text = '[provider]\napi_key = "k"\nbase_url = "u"\nmodel = "m"\n'
    out = remove_provider_field(text, "base_url")
    assert "base_url" not in out
    assert 'api_key = "k"' in out


def test_upsert_provider_field_model():
    text = '[provider]\napi_key = "k"\n'
    out = upsert_provider_field(text, "model", "x")
    assert 'model = "x"' in out


def test_needs_api_key():
    assert needs_api_key(ReplConfig()) is True
    assert needs_api_key(ReplConfig(api_key="sk-x")) is False

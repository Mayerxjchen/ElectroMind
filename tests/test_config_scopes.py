"""CLI-5：配置多 scope（User → Project → Local → CLI）+ Workspace Trust。

conftest 已隔离 HOME；项目目录建在 tmp_path/proj（与 home 不同目录）。
"""

from __future__ import annotations

from app.config import (
    RUN_OPTIONS_FIELD_KEYS,
    SETTINGS_FIELD_KEYS,
    find_project_root,
    is_project_trusted,
    load_config,
    load_settings_sources,
    merge_settings,
    trust_project,
    untrust_project,
)


def _make_project(tmp_path, *, with_local: bool = True, project_toml: str = ""):
    proj = tmp_path / "proj"
    (proj / ".git").mkdir(parents=True)
    (proj / ".electromind").mkdir()
    (proj / ".electromind" / "config.toml").write_text(
        project_toml or '[provider]\nmodel = "proj-model"\n',
        encoding="utf-8",
    )
    if with_local:
        (proj / ".electromind" / "config.local.toml").write_text(
            '[provider]\nmodel = "local-model"\n',
            encoding="utf-8",
        )
    return proj


def test_scope_ordering_and_provenance(tmp_path):
    proj = _make_project(tmp_path)
    sources = load_settings_sources(workdir=str(proj), include_project=True)
    assert [s.scope for s in sources] == ["default", "user", "project", "local"]
    merged, provenance = merge_settings(sources)
    assert merged.model == "local-model"  # local 覆盖 project/user
    assert provenance["model"] == "local"
    assert provenance["max_turns"] == "user"  # 模板物化的 user 字段


def test_local_overrides_project_overrides_user(tmp_path):
    proj = _make_project(tmp_path, with_local=False)
    sources = load_settings_sources(workdir=str(proj), include_project=True)
    merged, provenance = merge_settings(sources)
    assert merged.model == "proj-model"
    assert provenance["model"] == "project"


def test_cli_config_overrides_all(tmp_path):
    proj = _make_project(tmp_path)
    cli_file = tmp_path / "extra.toml"
    cli_file.write_text('[provider]\nmodel = "cli-model"\n', encoding="utf-8")
    sources = load_settings_sources(
        workdir=str(proj), config_path=cli_file, include_project=True
    )
    merged, provenance = merge_settings(sources)
    assert merged.model == "cli-model"
    assert provenance["model"] == "cli"


def test_project_scope_skipped_when_untrusted(tmp_path):
    """load_config fail-closed：未信任项目不加载 Project/Local 配置。"""
    proj = _make_project(tmp_path)
    config = load_config(workdir=str(proj))
    assert config.model == "deepseek-v4-flash"  # 模板默认，不是 proj-model
    assert config.resolved_permission_mode() == "prompt"


def test_trust_enables_project_scope(tmp_path):
    proj = _make_project(tmp_path)
    assert is_project_trusted(proj) is False
    trust_project(proj)
    assert is_project_trusted(proj) is True
    config = load_config(workdir=str(proj))
    assert config.model == "local-model"  # 信任后 local 生效
    untrust_project(proj)
    assert is_project_trusted(proj) is False
    assert load_config(workdir=str(proj)).model == "deepseek-v4-flash"


def test_project_scope_skipped_when_root_is_home(tmp_path):
    """dev 模式：home 就是项目目录 → project scope 不重复加载。"""
    home = tmp_path / ".electromind"
    home.mkdir(parents=True)
    (home / "config.toml").write_text('[provider]\nmodel = "home-model"\n')
    sources = load_settings_sources(workdir=str(tmp_path), include_project=True)
    assert [s.scope for s in sources] == ["default", "user"]


def test_find_project_root_walks_up(tmp_path):
    nested = tmp_path / "proj" / "sub" / "dir"
    (tmp_path / "proj" / ".git").mkdir(parents=True)
    nested.mkdir(parents=True)
    assert find_project_root(str(nested)) == (tmp_path / "proj").resolve()


def test_project_root_none_outside_repo(tmp_path):
    bare = tmp_path / "bare"
    bare.mkdir()
    assert find_project_root(str(bare)) is None


def test_field_key_maps_cover_settings():
    from app.config import Settings

    for field in Settings.__dataclass_fields__:
        if field == "subs":
            continue  # 特殊结构，不走点分键
        assert field in SETTINGS_FIELD_KEYS, field


def test_run_options_field_keys_for_sources():
    assert RUN_OPTIONS_FIELD_KEYS["mode"] == "execution.session_mode"
    assert RUN_OPTIONS_FIELD_KEYS["target"] == "execution.mode"
    assert RUN_OPTIONS_FIELD_KEYS["permission_mode"] == "permission.mode"


def test_permission_rules_from_trusted_project_apply(tmp_path):
    """信任后项目权限规则（permission.mode）生效。"""
    proj = _make_project(
        tmp_path,
        with_local=False,
        project_toml='[permission]\nmode = "auto-safe"\n',
    )
    assert load_config(workdir=str(proj)).resolved_permission_mode() == "prompt"
    trust_project(proj)
    assert load_config(workdir=str(proj)).resolved_permission_mode() == "auto-safe"

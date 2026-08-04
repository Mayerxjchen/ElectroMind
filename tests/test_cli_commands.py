"""CLI-1：顶层子命令（session/config/skills/version）+ cli.main 分派。"""

from __future__ import annotations

import json

import pytest

from app import cli
from app.commands import config as config_cmd
from app.commands import session as session_cmd
from app.commands import skills as skills_cmd
from app.exitcodes import EXIT_CLI, EXIT_OK


def _make_thread(tmp_path, thread_id: str = "thread-t1"):
    """在隔离 home 下创建一个真实 thread（thread.toml + workspaces/main）。"""
    from electromind.ithread.local import Thread
    from electromind.paths import activate_home

    activate_home("dev", tmp_path)
    return Thread.open(thread_id, overrides={"backend": "local"})


# ---------------------------------------------------------------------------
# session 子命令
# ---------------------------------------------------------------------------


def test_session_list_empty(capsys):
    assert session_cmd.run(["list"]) == EXIT_OK
    assert "(no sessions)" in capsys.readouterr().out


def test_session_list_default_action(capsys, tmp_path):
    _make_thread(tmp_path, "thread-a")
    assert session_cmd.run([]) == EXIT_OK
    out = capsys.readouterr().out
    assert "thread-a" in out


def test_session_show_detail(capsys, tmp_path):
    _make_thread(tmp_path, "thread-b")
    assert session_cmd.run(["show", "thread-b"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "thread_id:  thread-b" in out
    assert "directory:" in out


def test_session_show_missing(capsys):
    assert session_cmd.run(["show", "thread-nope"]) == EXIT_CLI
    assert "会话不存在" in capsys.readouterr().err


def test_session_delete(capsys, tmp_path):
    _make_thread(tmp_path, "thread-c")
    assert session_cmd.run(["delete", "thread-c"]) == EXIT_OK
    assert "已删除" in capsys.readouterr().out

    from app.sessions import find_session_by_id

    assert find_session_by_id("thread-c") is None


def test_session_export_writes_json(tmp_path, capsys, monkeypatch):
    _make_thread(tmp_path, "thread-d")
    monkeypatch.chdir(tmp_path)
    assert session_cmd.run(["export", "thread-d"]) == EXIT_OK
    payload = json.loads((tmp_path / "thread-d.json").read_text(encoding="utf-8"))
    assert payload["thread_id"] == "thread-d"
    assert "spec" in payload
    assert "messages" in payload
    assert "已导出" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# config 子命令
# ---------------------------------------------------------------------------


def _write_config(tmp_path, text: str):
    path = tmp_path / ".electromind"
    path.mkdir(exist_ok=True)
    (path / "config.toml").write_text(text, encoding="utf-8")


def test_config_path(capsys, tmp_path):
    _write_config(tmp_path, '[provider]\nmodel = "deepseek-v4-flash"\n')
    assert config_cmd.run(["path"]) == EXIT_OK
    assert capsys.readouterr().out.strip().endswith("config.toml")


def test_config_get_masked_api_key(capsys, tmp_path):
    _write_config(tmp_path, '[provider]\napi_key = "sk-secret-1234"\n')
    assert config_cmd.run(["get", "provider.api_key"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "1234" in out
    assert "sk-secret" not in out


def test_config_get_missing_key(capsys, tmp_path):
    _write_config(tmp_path, '[provider]\nmodel = "x"\n')
    assert config_cmd.run(["get", "provider.nope"]) == EXIT_CLI
    assert "未找到键" in capsys.readouterr().err


def test_config_set_roundtrip(capsys, tmp_path):
    _write_config(tmp_path, '[provider]\nmodel = "deepseek-v4-flash"\n')
    assert config_cmd.run(["set", "provider.model", "deepseek-v4-pro"]) == EXIT_OK
    capsys.readouterr()
    assert config_cmd.run(["get", "provider.model"]) == EXIT_OK
    assert capsys.readouterr().out.strip() == "deepseek-v4-pro"


def test_config_unset(capsys, tmp_path):
    _write_config(tmp_path, '[provider]\nmodel = "x"\n')
    assert config_cmd.run(["unset", "provider.model"]) == EXIT_OK
    capsys.readouterr()  # 清掉 unset 的输出
    # 删除后回落内置默认层（默认参与合并），不再是「缺失」。
    assert config_cmd.run(["get", "provider.model"]) == EXIT_OK
    assert capsys.readouterr().out.strip() == "deepseek-v4-flash"


def test_config_validate_ok(capsys, tmp_path):
    _write_config(tmp_path, '[provider]\nmodel = "x"\n')
    assert config_cmd.run(["validate"]) == EXIT_OK
    assert "配置有效" in capsys.readouterr().out


def test_config_validate_bad_value(capsys, tmp_path):
    _write_config(tmp_path, '[execution]\nmode = "cloud"\n')
    assert config_cmd.run(["validate"]) == EXIT_CLI
    assert "execution.mode" in capsys.readouterr().err


def test_config_sources_lists_keys(capsys, tmp_path):
    _write_config(tmp_path, '[provider]\nmodel = "x"\n[sandbox]\nbackend = "local"\n')
    assert config_cmd.run(["sources"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "provider.model" in out
    assert "sandbox.backend" in out


def test_config_sources_shows_scope_provenance(capsys, tmp_path, monkeypatch):
    """sources 显示每个生效键来自哪个作用域（user/project/local/cli）。"""
    from app.config import trust_project

    # user 作用域（隔离 HOME 的模板 api_key 为空 → 显式写一个）
    user_dir = tmp_path / ".electromind"
    user_dir.mkdir(exist_ok=True)
    (user_dir / "config.toml").write_text('[provider]\napi_key = "sk-user-1234"\n')
    proj = tmp_path / "proj"
    (proj / ".git").mkdir(parents=True)
    (proj / ".electromind").mkdir()
    (proj / ".electromind" / "config.toml").write_text(
        '[provider]\nmodel = "proj-model"\n[permission]\nmode = "auto-safe"\n',
        encoding="utf-8",
    )
    (proj / ".electromind" / "config.local.toml").write_text(
        '[provider]\nmodel = "local-model"\n',
        encoding="utf-8",
    )
    trust_project(proj)  # 信任后才生效
    monkeypatch.chdir(proj)

    from app.config import RunOptions

    assert (
        config_cmd.run(["sources"], options=RunOptions(permission_mode="prompt"))
        == EXIT_OK
    )
    out = capsys.readouterr().out
    rows = {}
    for line in out.splitlines():
        if "  " in line:
            key, scope = line.rsplit("  ", 1)
            rows[key.strip()] = scope.strip()
    assert rows["provider.model"] == "local"
    assert rows["permission.mode"] == "cli"  # CLI 覆盖（去重后只出现一次）
    assert rows["provider.api_key"] == "user"


def test_config_sources_skips_untrusted_project(capsys, tmp_path, monkeypatch):
    """未信任项目的配置不参与合并，并在 stderr 明确标注为已跳过。"""
    proj = tmp_path / "proj"
    (proj / ".git").mkdir(parents=True)
    (proj / ".electromind").mkdir()
    (proj / ".electromind" / "config.toml").write_text(
        '[provider]\nmodel = "proj-model"\n'
    )
    monkeypatch.chdir(proj)
    assert config_cmd.run(["sources"]) == EXIT_OK
    captured = capsys.readouterr()
    assert "proj-model" not in captured.out  # 未信任项目的值未进入生效视图
    assert "已跳过" in captured.err  # 明确标注未参与合并


def test_config_set_scope_project(capsys, tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    (proj / ".git").mkdir(parents=True)
    monkeypatch.chdir(proj)
    assert (
        config_cmd.run(["set", "provider.model", "proj-model", "--scope", "project"])
        == EXIT_OK
    )
    target = proj / ".electromind" / "config.toml"
    assert target.is_file()
    assert "proj-model" in target.read_text(encoding="utf-8")


def test_config_trust_untrust_roundtrip(capsys, tmp_path, monkeypatch):
    from app.config import is_project_trusted

    proj = tmp_path / "proj"
    (proj / ".git").mkdir(parents=True)
    monkeypatch.chdir(proj)
    assert config_cmd.run(["trust"]) == EXIT_OK
    assert is_project_trusted(proj) is True
    assert config_cmd.run(["untrust"]) == EXIT_OK
    assert is_project_trusted(proj) is False


# ---------------------------------------------------------------------------
# Workspace Trust 交互提示
# ---------------------------------------------------------------------------


def _project_with_config(tmp_path) -> object:
    proj = tmp_path / "proj"
    (proj / ".git").mkdir(parents=True)
    (proj / ".electromind").mkdir()
    (proj / ".electromind" / "config.toml").write_text(
        '[permission]\nmode = "auto-safe"\n'
    )
    return proj


def test_ensure_project_trust_yes_applies(monkeypatch, tmp_path, capsys):
    from app.commands.interactive import _ensure_project_trust
    from app.config import ReplConfig, RunOptions, is_project_trusted

    proj = _project_with_config(tmp_path)
    monkeypatch.chdir(proj)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "y")

    config = ReplConfig(api_key="sk-test")
    result = _ensure_project_trust(config, RunOptions())

    assert is_project_trusted(proj) is True
    assert result.resolved_permission_mode() == "auto-safe"  # 信任后项目权限生效
    assert result.api_key == "sk-test"  # 保留原 provider 字段


def test_ensure_project_trust_no_skips(monkeypatch, tmp_path, capsys):
    from app.commands.interactive import _ensure_project_trust
    from app.config import ReplConfig, RunOptions, is_project_trusted

    proj = _project_with_config(tmp_path)
    monkeypatch.chdir(proj)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")

    result = _ensure_project_trust(ReplConfig(api_key="sk-test"), RunOptions())

    assert is_project_trusted(proj) is False
    assert result.resolved_permission_mode() == "prompt"  # 项目配置未应用
    assert "已跳过" in capsys.readouterr().err


def test_ensure_project_trust_non_tty_skips_fail_closed(monkeypatch, tmp_path, capsys):
    from app.commands.interactive import _ensure_project_trust
    from app.config import ReplConfig, RunOptions

    proj = _project_with_config(tmp_path)
    monkeypatch.chdir(proj)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    result = _ensure_project_trust(ReplConfig(api_key="sk-test"), RunOptions())

    assert result.resolved_permission_mode() == "prompt"  # fail-closed
    assert "未信任的项目" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# skills 子命令
# ---------------------------------------------------------------------------


def test_skills_list_in_repo(capsys):
    """仓库自带 skills/ bundle（AICC 布局），list 应发现并输出。"""
    assert skills_cmd.run(["list"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "skill" in out.lower() or "(no skills discovered)" in out


def test_skills_list_empty_dir(capsys, monkeypatch, tmp_path):
    """空项目 + 无内置 bundle → 无 skills（SKILL-8 空环境发现测试）。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "electromind.skills.builtin._candidate_builtin_bases",
        lambda: [tmp_path / "none"],
    )
    assert skills_cmd.run(["list"]) == EXIT_OK
    assert "(no skills discovered)" in capsys.readouterr().out


def test_skills_show_missing(capsys):
    assert skills_cmd.run(["show", "nope"]) == EXIT_CLI
    assert "未找到 Skill" in capsys.readouterr().err


def test_skills_show_found(capsys, monkeypatch, tmp_path):
    """Characterization: ``skills show`` 命中时输出默认字段格式并返回 EXIT_OK。"""
    skill_dir = tmp_path / ".agents" / "skills" / "greet"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: greet\ndescription: Say hello\n---\nHello body.\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    assert skills_cmd.run(["show", "greet"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "name:        greet" in out
    assert "description: Say hello" in out
    assert "source:" in out
    assert "sha256:" in out
    assert "Hello body." in out


def test_skills_validate_ok(capsys, monkeypatch, tmp_path):
    """Characterization: 全部有效时 ``skills validate`` 返回 EXIT_OK。"""
    skill_dir = tmp_path / ".agents" / "skills" / "greet"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: greet\ndescription: Say hello\n---\nHello body.\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    assert skills_cmd.run(["validate"]) == EXIT_OK
    assert "校验通过" in capsys.readouterr().out


def test_skills_validate_reports_error(capsys, monkeypatch, tmp_path):
    """Characterization: 发现 error 级诊断时 ``skills validate`` 打印到 stderr 并返回 EXIT_CLI。"""
    skill_dir = tmp_path / ".agents" / "skills" / "bad name"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: bad name\ndescription: bad\n---\nBody.\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    assert skills_cmd.run(["validate"]) == EXIT_CLI
    assert "✗" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# version
# ---------------------------------------------------------------------------


def test_version_prints_version(capsys):
    from app.cli import print_version

    assert print_version() == EXIT_OK
    out = capsys.readouterr().out.strip()
    assert out and out != "0.0.0+unknown"


# ---------------------------------------------------------------------------
# cli.main 分派
# ---------------------------------------------------------------------------


def test_main_dispatches_session_subcommand(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["session", "list"])
    assert exc.value.code == 0
    assert "(no sessions)" in capsys.readouterr().out


def test_main_dispatches_print_mode(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    async def fake_run(config, options):
        captured["options"] = options
        return 0

    monkeypatch.setattr("app.commands.print_mode.run", fake_run)
    with pytest.raises(SystemExit) as exc:
        cli.main(["-p", "任务", "--output-format", "json"])
    assert exc.value.code == 0
    options = captured["options"]
    assert options.prompt == ("任务",)
    assert options.print_mode is True
    assert options.output_format == "json"


def test_main_dispatches_interactive_with_prompt(monkeypatch):
    captured: dict[str, object] = {}

    def fake_run(config, options):
        captured["options"] = options
        return 0

    monkeypatch.setattr("app.commands.interactive.run", fake_run)
    with pytest.raises(SystemExit) as exc:
        cli.main(["检查这个项目"])
    assert exc.value.code == 0
    assert captured["options"].prompt == ("检查这个项目",)


def test_main_deprecation_warning_on_stderr(monkeypatch, capsys):
    def fake_run(config, options):
        return 0

    monkeypatch.setattr("app.commands.interactive.run", fake_run)
    with pytest.raises(SystemExit):
        cli.main(["--auto", "任务"])
    assert "--auto/--yolo 已弃用" in capsys.readouterr().err


def test_main_wire_dispatch(monkeypatch):
    """--wire 后端模式分派（行为保持兼容）。"""

    async def fake_wire(config):
        raise SystemExit(7)

    monkeypatch.setattr("app.wire.run_wire", fake_wire)
    with pytest.raises(SystemExit) as exc:
        cli.main(["--wire"])
    assert exc.value.code == 7


def test_subcommand_flag_detach():
    """顶层已知 flag（--port/--host）在子命令位置时归子命令。"""
    from app.cli import _detach_subcommand_flags

    assert _detach_subcommand_flags(
        ["service", "start", "--port", "18999"], "service"
    ) == ["--port", "18999"]
    assert _detach_subcommand_flags(
        ["config", "sources", "--port", "1", "--host", "x"], "config"
    ) == ["--port", "1", "--host", "x"]
    assert _detach_subcommand_flags(["service", "start"], "service") == []


def test_main_version_flag(capsys):
    from app import exitcodes

    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == exitcodes.EXIT_OK
    out = capsys.readouterr().out.strip()
    assert out and out != "0.0.0+unknown"


def test_main_internal_error_hides_traceback(capsys, monkeypatch):
    """默认错误不输出完整 traceback（exit 8）。"""
    from app import exitcodes

    def boom(config, options):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.commands.interactive.run", boom)
    with pytest.raises(SystemExit) as exc:
        cli.main(["任务"])
    assert exc.value.code == exitcodes.EXIT_UNKNOWN
    err = capsys.readouterr().err
    assert "内部错误: RuntimeError: boom" in err
    assert "Traceback" not in err


def test_main_debug_shows_traceback(capsys, monkeypatch):
    """--debug 才输出完整 traceback。"""
    from app import exitcodes

    def boom(config, options):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.commands.interactive.run", boom)
    with pytest.raises(SystemExit) as exc:
        cli.main(["--debug", "任务"])
    assert exc.value.code == exitcodes.EXIT_UNKNOWN
    assert "Traceback" in capsys.readouterr().err

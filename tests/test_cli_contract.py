"""CLI-0 契约冻结：Flag 面、默认值、Exit Code、弃用策略、Settings/RunOptions 合并。

契约正文见 docs/superpowers/specs/2026-08-01-cli-professional-refactor.md。
"""

from __future__ import annotations

import os

import pytest

from app import exitcodes
from app.cli_parser import (
    INPUT_FORMATS,
    MODES,
    OUTPUT_FORMATS,
    PERMISSION_MODES,
    SUBCOMMANDS,
    TARGETS,
    build_parser,
    deprecation_warnings,
)
from app.config import (
    ReplConfig,
    RunOptions,
    Settings,
    parse_settings,
)

# ---------------------------------------------------------------------------
# Exit Code 契约
# ---------------------------------------------------------------------------


def test_exit_codes_contract_frozen():
    assert exitcodes.EXIT_OK == 0
    assert exitcodes.EXIT_CLI == 2
    assert exitcodes.EXIT_PROVIDER == 3
    assert exitcodes.EXIT_PERMISSION == 4
    assert exitcodes.EXIT_EXECUTION == 5
    assert exitcodes.EXIT_CANCELLED == 6
    assert exitcodes.EXIT_SERVICE == 7
    assert exitcodes.EXIT_UNKNOWN == 8


# ---------------------------------------------------------------------------
# Flag 面与默认值
# ---------------------------------------------------------------------------


def test_parser_surface_frozen():
    parser = build_parser()
    args = parser.parse_args([])
    # 三维正交维度默认值（运行时解析为 run / sandbox / prompt）
    assert args.mode is None
    assert args.target is None
    assert args.permission_mode is None
    # 输出契约默认值
    assert args.output_format == "text"
    assert args.input_format == "text"
    # 兼容 flag 存在
    assert args.wire is False
    assert args.http is False
    assert args.blocking is False
    assert args.continue_last is False
    assert args.resume is None


def test_choices_frozen():
    assert MODES == ("ask", "plan", "run")
    assert TARGETS == ("sandbox", "local", "ssh")
    assert "auto-safe" in PERMISSION_MODES
    assert OUTPUT_FORMATS == ("text", "json", "stream-json")
    assert INPUT_FORMATS == ("text", "stream-json")


def test_subcommands_surface():
    for name in (
        "session",
        "config",
        "skills",
        "doctor",
        "version",
        "app",
        "service",
        "completion",
    ):
        assert name in SUBCOMMANDS


def test_invalid_mode_rejected_with_exit_2():
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--mode", "explode"])
    assert exc.value.code == 2


def test_invalid_target_rejected_with_exit_2():
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--target", "cloud"])
    assert exc.value.code == 2


def test_short_flags_parse():
    args = build_parser().parse_args(["-p", "任务", "-c"])
    assert args.print_mode is True
    assert args.prompt == ["任务"]
    assert args.continue_last is True


def test_resume_optional_value():
    assert build_parser().parse_args(["-r"]).resume == ""
    assert build_parser().parse_args(["-r", "thread-1"]).resume == "thread-1"


# ---------------------------------------------------------------------------
# 弃用策略
# ---------------------------------------------------------------------------


def test_auto_yolo_deprecation_warning():
    args = build_parser().parse_args(["--auto"])
    warnings = deprecation_warnings(["--auto"], args)
    assert any("--auto/--yolo 已弃用" in w for w in warnings)


def test_execution_mode_deprecation_warning():
    args = build_parser().parse_args(["--execution-mode", "local"])
    warnings = deprecation_warnings(["--execution-mode", "local"], args)
    assert any("--execution-mode 已弃用" in w for w in warnings)


def test_max_turns_deprecation_warning():
    args = build_parser().parse_args(["--max-turns", "5"])
    warnings = deprecation_warnings(["--max-turns", "5"], args)
    assert any("--max-turns 已弃用" in w for w in warnings)
    assert args.max_iterations == 5  # 仍作为兼容别名生效


def test_permission_mode_auto_preserved_as_distinct_mode():
    """冻结契约（config.resolved_permission_mode 文档）：auto 是 --yolo 遗留
    语义（全部放行），与 auto-safe（仅安全操作）保持区分，不做归一化。"""
    args = build_parser().parse_args(["--permission-mode", "auto"])
    assert args.permission_mode == "auto"


# ---------------------------------------------------------------------------
# Settings / RunOptions 合并
# ---------------------------------------------------------------------------


def test_settings_to_repl_config_roundtrip():
    settings = parse_settings(
        {
            "provider": {"model": "deepseek-v4-flash"},
            "execution": {"mode": "ssh", "session_mode": "plan"},
            "permission": {"mode": "auto-safe"},
        }
    )
    config = settings.to_repl_config()
    assert config.model == "deepseek-v4-flash"
    assert config.execution_mode == "ssh"
    assert config.session_mode == "plan"
    # auto-safe 与 auto 区分：auto-safe 只自动放行安全操作
    assert config.resolved_permission_mode() == "auto-safe"


def test_settings_auto_safe_accepted():
    settings = parse_settings({"permission": {"mode": "auto-safe"}})
    assert settings.permission_mode == "auto-safe"


def test_settings_invalid_execution_mode_rejected():
    with pytest.raises(ValueError, match="execution.mode"):
        parse_settings({"execution": {"mode": "cloud"}})


def test_run_options_apply_cli_over_file():
    config = ReplConfig(model="deepseek-v4-flash", max_turns=24)
    options = RunOptions(
        mode="ask",
        target="local",
        permission_mode="auto-safe",
        model="deepseek-v4-pro",
        max_iterations=10,
    )
    merged = options.apply_to(config)
    assert merged.session_mode == "ask"
    assert merged.execution_mode == "local"
    assert merged.resolved_permission_mode() == "auto-safe"
    assert merged.permission_auto_safe() is True
    assert merged.model == "deepseek-v4-pro"
    assert merged.max_turns == 10


def test_run_options_project_normalized_absolute():
    merged = RunOptions(project="~/projects/x").apply_to(ReplConfig())
    assert merged.project_path == os.path.abspath(os.path.expanduser("~/projects/x"))


def test_run_options_disallowed_tools_filter_defaults():
    merged = RunOptions(disallowed_tools=("fetch_url",)).apply_to(ReplConfig())
    assert "fetch_url" not in merged.resolved_agent_tools()
    assert "web_search" in merged.resolved_agent_tools()


def test_run_options_allowed_tools_override():
    merged = RunOptions(allowed_tools=("web_search",)).apply_to(ReplConfig())
    assert merged.resolved_agent_tools() == ("web_search",)


def test_session_mode_run_maps_to_write_capable_agent():
    assert ReplConfig(session_mode="run").thread_overrides()["session_mode"] == "agent"
    assert ReplConfig(session_mode="plan").thread_overrides()["session_mode"] == "plan"
    assert ReplConfig(session_mode="ask").thread_overrides()["session_mode"] == "ask"


def test_from_args_target_prefers_target_over_execution_mode():
    parser = build_parser()
    args = parser.parse_args(["--target", "ssh", "--execution-mode", "local"])
    options = RunOptions.from_args(args)
    assert options.target == "ssh"  # 新 flag 优先


def test_inline_flag_flows_to_config():
    parser = build_parser()
    args = parser.parse_args(["--inline"])
    merged = RunOptions.from_args(args).apply_to(ReplConfig())
    assert merged.inline is True
    assert ReplConfig().inline is False


def test_about_flag_parses():
    args = build_parser().parse_args(["--about"])
    assert args.about is True


def test_settings_is_distinct_from_run_options():
    """Settings 只承载持久化字段；RunOptions 承载每次运行字段。

    两处都能设置的字段（model/permission_mode/backend/ssh_*）允许重叠；
    运行期专属字段（prompt/print_mode/output_format/mode/target 等）只属于 RunOptions。
    """
    settings_fields = set(Settings.__dataclass_fields__)
    for run_only in (
        "prompt",
        "print_mode",
        "mode",
        "target",
        "add_dirs",
        "max_iterations",
        "allowed_tools",
        "disallowed_tools",
        "no_session_persistence",
        "output_format",
        "input_format",
        "quiet",
        "verbose",
        "debug",
        "log_file",
        "continue_last",
        "resume",
        "resume_interactive",
        "deprecated_auto",
        "wire",
        "http",
    ):
        assert run_only not in settings_fields, run_only
    # 文件专属字段不在 RunOptions 里
    for file_only in ("api_key", "container_ttl", "skill_roots", "agent_tools", "subs"):
        assert file_only not in RunOptions.__dataclass_fields__, file_only

"""``electromind doctor``：定位常见环境问题。

基础版检查：版本、配置来源、Provider Key、执行目标解析、Skills 发现、数据目录。
CLI-5 会扩展 Sandbox runtime / Container image / SSH config / 协议版本等检查。
"""

from __future__ import annotations

import os  # noqa: F401 — os.access/isfile/expanduser（注意：勿改成函数内 import，会变成局部变量）
import sys
from dataclasses import dataclass, field


@dataclass
class Check:
    name: str
    ok: bool = True
    detail: str = ""


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append(Check(name=name, ok=ok, detail=detail))

    @property
    def failed(self) -> bool:
        return any(not check.ok for check in self.checks)


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("electromind")
    except Exception:
        return "unknown"


def collect_checks() -> Report:
    from electromind.paths import default_electromind_home, home_config_path

    report = Report()
    report.add("CLI 版本", True, _version())

    home = default_electromind_home()
    config_path = home_config_path()
    if config_path.is_file():
        try:
            from app.config import load_config

            load_config()
            report.add("配置", True, str(config_path))
        except Exception as exc:
            report.add("配置", False, f"{type(exc).__name__}: {exc}")
    else:
        report.add("配置", False, f"配置文件不存在: {config_path}")

    try:
        from app.config import load_config

        if load_config().resolved_api_key():
            report.add("Provider Key", True, "已配置")
        else:
            report.add("Provider Key", False, "缺少 API Key（DEEPSEEK_API_KEY 或配置）")
    except Exception as exc:
        report.add("Provider Key", False, str(exc))

    # 模型可用性：名称已知（能解析上下文窗口）才算可判；live 可用性需实际 Run。
    try:
        from app.config import load_config

        model = load_config().resolved_model()
        from electromind.core.context_limit import resolve_context_limit

        limit = resolve_context_limit(model)
        known = limit != 128_000 or any(
            key in model.lower() for key in ("deepseek", "gpt", "claude", "o1", "o3")
        )
        report.add(
            "模型",
            bool(model) and known,
            f"{model} · ctx {limit}",
        )
    except Exception as exc:
        report.add("模型", False, f"{type(exc).__name__}: {exc}")

    try:
        from app.config import (
            find_project_root,
            is_project_trusted,
            load_config,
            load_settings_sources,
        )

        config = load_config()
        target = config.execution_mode or "sandbox"

        # 配置作用域栈 + Workspace Trust
        root = find_project_root()
        scopes = [s.scope for s in load_settings_sources(include_project=True)]
        if root is not None and any(s in ("project", "local") for s in scopes):
            if is_project_trusted(root):
                report.add("Workspace Trust", True, f"{root} 已信任")
            else:
                report.add(
                    "Workspace Trust",
                    False,
                    f"{root} 未信任：Project/Local 配置已跳过（config trust 启用）",
                )
        else:
            report.add("Workspace Trust", True, "无 Project/Local 配置")
        from electromind.execution import resolve_execution

        resolved = resolve_execution(target)
        report.add("执行目标", True, f"{resolved.mode} ({resolved.resolved_backend})")

        # Container / SSH 专项检查（仅当配置了对应目标时）
        if target == "sandbox" and resolved.resolved_backend in ("docker", "podman"):
            report.add("Container", True, f"{resolved.resolved_backend} 可用")
        elif target == "ssh":
            ssh_config = config.ssh_config or "~/.ssh/config"
            path = os.path.expanduser(ssh_config)
            if config.ssh_host:
                if os.path.isfile(path):
                    report.add("SSH", True, f"{config.ssh_host} · {path}")
                else:
                    report.add("SSH", False, f"SSH config 不存在: {path}")
            else:
                report.add("SSH", False, "ssh_host 未配置")
        else:
            report.add("Container", True, "sandbox 目标未启用（跳过探测）")
    except Exception as exc:
        report.add("执行目标", False, str(exc))

    try:
        from app.commands.skills import _catalog

        catalog = _catalog()
        errors = [d for d in catalog.diagnostics if d.severity == "error"]
        detail = f"{len(catalog.registry.names())} 个 Skill" + (
            f"，{len(errors)} 个错误" if errors else ""
        )
        report.add("Skills", not errors, detail)
    except Exception as exc:
        report.add("Skills", False, str(exc))

    writable = os.access(home, os.W_OK) if home.is_dir() else False
    report.add("数据目录", writable, str(home))

    # Service / Harness 协议（wire/http 与 CLI 客户端共用同一协议层）
    try:
        from electromind.harness.protocol_v2 import EventEnvelope

        field = EventEnvelope.__dataclass_fields__.get("protocol_version")
        protocol_version = field.default if field is not None else None
        report.add(
            "Service 协议",
            protocol_version == 2,
            f"protocol v{protocol_version}（wire/http/CLI 共用）",
        )
    except Exception as exc:
        report.add("Service 协议", False, f"{type(exc).__name__}: {exc}")

    # Service 运行状态：有 PID 文件 → 存活 + /health；无 → 未运行（可选，不算失败）
    try:
        from app.commands import service as service_cmd

        pid = service_cmd._read_pid()
        if pid is None:
            report.add("Service 状态", True, "未运行（可选；service start 启动）")
        elif not service_cmd._alive(pid):
            report.add("Service 状态", False, f"PID {pid} 不存活（陈旧 PID 文件）")
        else:
            import urllib.request

            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{service_cmd.DEFAULT_PORT}/health", timeout=2
                ):
                    report.add("Service 状态", True, f"运行中（PID {pid}）")
            except Exception:
                report.add("Service 状态", False, f"PID {pid} 存活但 /health 不可达")
    except Exception as exc:
        report.add("Service 状态", False, f"{type(exc).__name__}: {exc}")

    # 日志目录：--log-file 目标可写（未指定时检查 home 根可写）
    log_target = os.environ.get("ELECTROMIND_LOG_FILE")
    if log_target:
        log_dir = os.path.dirname(log_target) or "."
        report.add(
            "日志目录",
            os.path.isdir(log_dir) and os.access(log_dir, os.W_OK),
            log_target,
        )
    else:
        report.add("日志目录", writable, "未指定 --log-file（使用 stderr）")

    return report


def run(argv: list[str]) -> int:
    del argv
    report = collect_checks()
    for check in report.checks:
        mark = "ok " if check.ok else "FAIL"
        line = f"[{mark}] {check.name}: {check.detail}"
        print(line, file=sys.stderr if not check.ok else sys.stdout)
    if report.failed:
        print("发现问题：请根据上方 FAIL 项处理。", file=sys.stderr)
        return 1
    print("一切正常。")
    return 0

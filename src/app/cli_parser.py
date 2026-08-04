"""CLI 参数解析 — 全部 Flag 契约集中于此（冻结见 docs/superpowers/specs/2026-08-01-cli-professional-refactor.md）。

设计说明：不启用 argparse subparsers（subparsers 会贪婪吞掉第一个位置参数，
导致 ``electromind "提示词"`` 无法与 ``electromind session list`` 共存）。
顶层 ``prompt`` 是 ``nargs="*"`` 位置参数；cli.py 依据第一个 token 手动分发子命令。

本模块不 import config，避免循环依赖；config.py 转发 build_parser 以保持旧调用兼容。
"""

from __future__ import annotations

import argparse

MODES = ("ask", "plan", "run")
TARGETS = ("sandbox", "local", "ssh")
# 兼容迁移：旧值 auto 是已弃用别名，解析时归一化为 auto-safe（见下方 type）。
PERMISSION_MODES = ("prompt", "auto-safe", "auto")
OUTPUT_FORMATS = ("text", "json", "stream-json")
INPUT_FORMATS = ("text", "stream-json")

# 顶层子命令：``electromind <name> ...``。各命令在 commands/ 下拥有自己的 parser。
SUBCOMMANDS = (
    "session",
    "config",
    "skills",
    "doctor",
    "version",
    "app",
    "service",
    "completion",
)

DEFAULT_OUTPUT_FORMAT = "text"
DEFAULT_INPUT_FORMAT = "text"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="electromind",
        description=(
            "electromind agent CLI — 交互、脚本、恢复、权限、配置与诊断共用同一入口。"
            "子命令: " + " | ".join(SUBCOMMANDS)
        ),
    )
    parser.add_argument(
        "prompt",
        nargs="*",
        help="初始任务（交互模式立即执行）；与 -p 组合为非交互任务文本",
    )
    parser.add_argument(
        "-c",
        "--continue",
        dest="continue_last",
        action="store_true",
        help="恢复当前项目最近一次会话",
    )
    parser.add_argument(
        "-r",
        "--resume",
        nargs="?",
        const="",
        default=None,
        metavar="THREAD_ID",
        help="恢复指定会话；无参数时打开交互式选择器",
    )
    parser.add_argument(
        "-p",
        "--print",
        dest="print_mode",
        action="store_true",
        help="非交互执行：完成任务后退出（无 prompt 时读 stdin）",
    )
    parser.add_argument(
        "--mode",
        choices=MODES,
        default=None,
        help="任务模式：ask 只读分析 | plan 只读检查并生成计划 | run 可请求写入和执行（默认 run）",
    )
    parser.add_argument(
        "--target",
        choices=TARGETS,
        default=None,
        help="执行目标：sandbox（默认，容器）| local（需显式选择）| ssh（远程）",
    )
    parser.add_argument(
        "--permission-mode",
        choices=PERMISSION_MODES,
        default=None,
        help="权限模式：prompt（默认，逐次审批）| auto-safe（仅自动通过后端判定安全的操作）"
        "| auto（遗留 --yolo 语义，全部放行）",
    )
    parser.add_argument(
        "--project",
        default=None,
        help="绑定本次会话的用户目录（host_root）；存为绝对路径，避免 resume 漂移",
    )
    parser.add_argument(
        "--add-dir",
        action="append",
        default=None,
        metavar="PATH",
        help="附加绑定目录（保留给未来沙箱绑定；当前仅记录）",
    )
    parser.add_argument(
        "--model", default=None, help="覆盖模型（如 deepseek-v4-flash）"
    )
    parser.add_argument(
        "--max-iterations",
        dest="max_iterations",
        type=int,
        default=None,
        help="单次 Run 的最大 Agent 轮数（默认 24）",
    )
    parser.add_argument(
        "--max-turns",
        dest="max_iterations",
        type=int,
        default=None,
        help="--max-iterations 的兼容别名（弃用，仅提示）",
    )
    parser.add_argument(
        "--input-format",
        choices=INPUT_FORMATS,
        default=DEFAULT_INPUT_FORMAT,
        help="输入格式：text（默认，stdin 原文）| stream-json（NDJSON 命令流）",
    )
    parser.add_argument(
        "--output-format",
        choices=OUTPUT_FORMATS,
        default=DEFAULT_OUTPUT_FORMAT,
        help="输出格式：text（默认，仅最终结果）| json（结构化结果）| stream-json（每行一个事件）",
    )
    parser.add_argument(
        "--allowed-tools",
        action="append",
        default=None,
        metavar="TOOL",
        help="harness 工具白名单（覆盖默认 web 工具，可多次传入）",
    )
    parser.add_argument(
        "--disallowed-tools",
        action="append",
        default=None,
        metavar="TOOL",
        help="从默认工具中剔除（如 fetch_url，可多次传入）",
    )
    parser.add_argument(
        "--no-session-persistence",
        action="store_true",
        help="不写会话 metainfo 与历史（自动化场景）",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="禁用 ANSI 颜色",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="减少 stderr 进度输出（非交互模式）",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="stderr 输出更多细节",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="stderr 输出 Debug 日志",
    )
    parser.add_argument(
        "--log-file", default=None, metavar="PATH", help="诊断日志写入文件"
    )
    parser.add_argument(
        "--inline",
        action="store_true",
        help="交互不进入 alternate screen，保留终端 scrollback（远程/tmux/日志录制）",
    )
    parser.add_argument(
        "--about",
        action="store_true",
        help="显示版本与 Logo 后退出",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="显示版本后退出",
    )

    # ---- 既有兼容 Flag（Desktop / 插件 / 旧脚本） ----
    parser.add_argument(
        "--config",
        default=None,
        help="extra config file over bundled + active home ({./.electromind|~/.electromind}/config.toml)",
    )
    parser.add_argument(
        "--thread-id",
        default=None,
        help="resume thread; omit to create thread-<timestamp>",
    )
    parser.add_argument(
        "--blocking",
        action="store_true",
        help="阻塞 REPL：跑完一轮再显示输入（默认 TTY 为底栏固定输入）",
    )
    parser.add_argument(
        "--auto",
        "--yolo",
        dest="deprecated_auto",
        action="store_true",
        help="(弃用) 危险工具全部自动审批，等同 --permission-mode auto（遗留语义）；后续版本移除 --yolo",
    )
    parser.add_argument(
        "--wire",
        action="store_true",
        help="stdio NDJSON 后端模式：stdin 收 JSON 命令，stdout 出事件流（供插件/前端驱动）",
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="HTTP 后端模式：POST /command 收命令，GET /events 出 SSE 事件流（对齐 wire）",
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="--http 监听地址（默认 127.0.0.1）"
    )
    parser.add_argument(
        "--port", type=int, default=8848, help="--http 监听端口（默认 8848）"
    )
    parser.add_argument(
        "--execution-mode",
        choices=TARGETS,
        default=None,
        help="(弃用) 等同 --target；后续版本移除",
    )
    parser.add_argument(
        "--backend",
        choices=("local", "container", "docker", "podman", "ssh"),
        default=None,
        help="覆盖 sandbox backend",
    )
    parser.add_argument(
        "--dev",
        nargs="?",
        const=".",
        default=None,
        metavar="ROOT",
        help="开发模式：数据落到 <ROOT>/.electromind（默认 ./.electromind）；不带则生产模式用 ~/.electromind",
    )
    parser.add_argument("--ssh-host", default=None, help="覆盖 SSH Host 别名")
    parser.add_argument("--ssh-config", default=None, help="覆盖 SSH config 路径")
    return parser


def deprecation_warnings(argv: list[str], args: argparse.Namespace) -> list[str]:
    """CLI 弃用告警（vNext 周期：仍可用，但打印警告；后续版本移除）。"""
    warnings: list[str] = []
    if args.deprecated_auto:
        warnings.append(
            "--auto/--yolo 已弃用：将映射为 --permission-mode auto（遗留语义，全部放行）；"
            "后续版本将移除 --yolo"
        )
    if "--execution-mode" in argv:
        warnings.append("--execution-mode 已弃用：请改用 --target")
    if "--max-turns" in argv:
        warnings.append("--max-turns 已弃用：请改用 --max-iterations")
    # --permission-mode auto 的弃用警告在 argparse normalize 时已打印
    return warnings

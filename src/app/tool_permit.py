"""危险工具审批 — run_command、copy_from_host。"""

from __future__ import annotations

import asyncio
import json

from electromind import Runner, ToolCallBegin, ToolDecision, ToolHooks
from electromind.runtime.hooks import ToolHookContext

from .terminal import emit, emit_prompt

DIM = "\033[90m"
YELLOW = "\033[33m"
RESET = "\033[0m"


def _c(text: str, code: str, *, on: bool) -> str:
    return f"{code}{text}{RESET}" if on else text


PERMIT_TOOLS = frozenset({"run_command", "copy_from_host"})

USER_DENIED_TOOL_MESSAGE = "用户拒绝了此工具调用。"

# Tool 完整输出上限：主时间线只渲染摘要，完整日志按需打开
MAX_TOOL_OUTPUT_CHARS = 20_000


def needs_tool_permit(tool_name: str) -> bool:
    return tool_name in PERMIT_TOOLS


def runner_supports_permit(runner: object) -> bool:
    return hasattr(runner, "inbound")


def risk_hint(command: str) -> str:
    """关键词级风险提示（Approval Card 展示用；auto-safe 判定见 ``_command_safe``）。"""
    lowered = command.lower()
    if "rm -" in lowered or lowered.startswith("rm "):
        return "deletes files"
    if "sudo" in lowered:
        return "elevated privileges"
    if ">" in command or "tee " in lowered:
        return "writes files"
    return "executes command"


# auto-safe 白名单：可证明只读的检查命令。
# 故意排除：解释器（python/perl/ruby/...）、下载器（curl/wget）、chmod/chown、
# git（可写）、sed/awk（sed -i / awk 重定向可写）——无法证明只读 → 一律需审批。
AUTO_SAFE_COMMANDS = frozenset(
    {
        "cat",
        "head",
        "tail",
        "more",
        "zcat",
        "ls",
        "find",
        "grep",
        "egrep",
        "fgrep",
        "which",
        "whereis",
        "uname",
        "hostname",
        "whoami",
        "id",
        "pwd",
        "echo",
        "date",
        "wc",
        "sort",
        "uniq",
        "cut",
        "diff",
        "cmp",
        "file",
        "stat",
        "df",
        "du",
        "free",
        "uptime",
        "ps",
        "lscpu",
        "nproc",
        "sinfo",
        "squeue",
        "sacct",
        "true",
        "false",
        "test",
        "[",
        "printf",
        "md5sum",
        "sha1sum",
        "sha256sum",
        "realpath",
        "readlink",
        "basename",
        "dirname",
        "fold",
        "nl",
        "od",
        "xxd",
        "seq",
        "tr",
        "comm",
        "paste",
        "join",
        "column",
        "expand",
        "unexpand",
        "fmt",
        "tac",
        "rev",
    }
)


# 白名单命令自身的危险参数（出现任一 → 需审批）。
# 覆盖复验样例：find -delete / find -exec / sort -o / xxd -r。
_UNSAFE_ARG_MARKERS: dict[str, tuple[str, ...]] = {
    "find": ("-delete", "-exec", "-execdir", "-ok", "-fprint", "-fls", "-fprintf"),
    "sort": ("-o",),
    "xxd": ("-r",),
}


# Shell 元字符：未加引号出现任一 → 无法证明只读
# （重定向/管道/命令替换/序列执行/大括号展开/通配符/波浪号）
_UNSAFE_METACHARS = ("|", ">", "<", ";", "&", "`", "$(", "{", "}", "*", "?", "~")


def _has_unquoted_metachar(command: str) -> bool:
    """引号感知的元字符扫描：引号内的 ``"*.py"`` 等不算（find -name 保持安全）。"""
    quote: str | None = None
    i = 0
    while i < len(command):
        ch = command[i]
        if quote is not None:
            if ch == quote:
                quote = None
            elif ch == "\\" and quote == '"':
                i += 1
        else:
            if ch in ("'", '"'):
                quote = ch
            elif ch in _UNSAFE_METACHARS:
                return True
        i += 1
    return False


def _command_safe(name: str, arguments: str) -> bool:
    """auto-safe 的“后端判定为安全”：仅可证明只读的命令自动放行。

    - 命令必须命中只读白名单（python/curl/chmod/git 等一律需审批）
    - 未加引号的 shell 元字符（重定向/管道/命令替换/通配符等）→ 需审批
    - copy_from_host 等非 run_command 无法判定副作用 → 需审批
    """
    if name != "run_command":
        return False
    try:
        payload = json.loads(arguments)
    except json.JSONDecodeError:
        return False
    command = payload.get("command") if isinstance(payload, dict) else None
    if not isinstance(command, str) or not command.strip():
        return False
    if _has_unquoted_metachar(command):
        return False
    try:
        import shlex

        argv = shlex.split(command)
    except ValueError:
        return False
    if not argv:
        return False
    if argv[0] not in AUTO_SAFE_COMMANDS:
        return False
    # 白名单命令自身的危险参数（find -delete / sort -o / xxd -r 等）
    markers = _UNSAFE_ARG_MARKERS.get(argv[0], ())
    if markers and any(marker in command for marker in markers):
        return False
    return True


def is_safe_tool_call(event: ToolCallBegin) -> bool:
    return _command_safe(event.name, event.arguments)


def requires_permit_prompt(permission_mode: str, event: ToolCallBegin) -> bool:
    """审批决策：prompt 全审批；auto-safe 只自动放行安全命令；auto 全放行。"""
    if permission_mode == "auto":
        return False
    if not needs_tool_permit(event.name):
        return False
    if permission_mode == "auto-safe" and is_safe_tool_call(event):
        return False
    return True


def summarize_tool_args(name: str, arguments: str) -> str:
    try:
        payload = json.loads(arguments)
    except json.JSONDecodeError:
        return arguments
    if name == "run_command":
        command = payload.get("command")
        return command if isinstance(command, str) else arguments
    if name == "copy_from_host":
        host_path = payload.get("host_path", "?")
        dest = payload.get("dest", ".")
        return f"{host_path} → {dest}"
    return arguments


def format_permit_prompt(event: ToolCallBegin) -> str:
    detail = summarize_tool_args(event.name, event.arguments)
    return f"审批 {event.name}：{detail}"


def parse_permit_answer(text: str) -> bool | None:
    word = text.strip().lower()
    if word in {"y", "yes", "是", "好", "ok", "批准", "同意"}:
        return True
    if word in {"n", "no", "否", "不", "拒绝", "deny"}:
        return False
    return None


def _arguments_digest(arguments: str) -> str:
    """与 wire 审批时一致的参数摘要（sha256 of sorted JSON）。"""
    import hashlib
    import json

    try:
        normalized = json.dumps(
            json.loads(arguments), ensure_ascii=False, sort_keys=True
        )
    except (json.JSONDecodeError, TypeError):
        normalized = str(arguments)
    return hashlib.sha256(normalized.encode()).hexdigest()


def apply_permit_answer(runner: Runner, tool_call_id: str, approved: bool) -> None:
    if approved:
        runner.inbound.permit(tool_call_id)
    else:
        runner.inbound.deny(tool_call_id, reason=USER_DENIED_TOOL_MESSAGE)


def _make_require_tool_permit(*, auto_safe: bool = False):
    async def require_tool_permit(ctx: ToolHookContext) -> ToolDecision | None:
        if not needs_tool_permit(ctx.name):
            return None
        if auto_safe and _command_safe(ctx.name, ctx.arguments):
            return None  # auto-safe：后端判定为安全的操作自动放行
        result = await ctx.runner.wait_tool_permit(ctx.tool_call_id)
        if not result.approved:
            message = result.reason.strip() or USER_DENIED_TOOL_MESSAGE
            return ToolDecision.deny(message)
        # P0-4: 执行前校验参数摘要——审批后参数被修改则拒绝执行
        check = getattr(ctx.runner, "check_approved_arguments", None)
        if callable(check):
            digest = _arguments_digest(ctx.arguments)
            if not check(ctx.tool_call_id, digest):
                return ToolDecision.deny(
                    "工具参数在审批后被修改，拒绝执行（请重新审批）"
                )
        return None

    return require_tool_permit


def build_app_tool_hooks(
    *, auto: bool = False, auto_safe: bool = False
) -> ToolHooks | None:
    """审批钩子：

    - ``auto``（--yolo/--auto 遗留语义）：无钩子，全部放行（仅剩 sandbox 模式/策略门）
    - ``auto_safe``：只自动放行后端判定为安全的操作，其余仍走审批
    - 默认 prompt：run_command / copy_from_host 全部走审批
    """
    if auto:
        return None
    return ToolHooks(before=[_make_require_tool_permit(auto_safe=auto_safe)])


async def prompt_permit_blocking(
    runner: Runner, event: ToolCallBegin, *, color: bool
) -> None:
    emit(_c(f"{format_permit_prompt(event)} [y/N]", YELLOW, on=color))
    while True:
        line = await asyncio.to_thread(emit_prompt, "permit> ")
        answer = parse_permit_answer(line)
        if answer is None:
            emit(_c("输入 y 批准 / n 拒绝", DIM, on=color))
            continue
        apply_permit_answer(runner, event.tool_call_id, answer)
        label = "已批准" if answer else "已拒绝"
        emit(_c(label, DIM, on=color))
        return


async def wait_for_layout_permit(
    runner: Runner,
    event: ToolCallBegin,
    run_state: dict,
    *,
    color: bool,
) -> None:
    emit(_c(f"{format_permit_prompt(event)} [y/N]", YELLOW, on=color))
    run_state["permit"] = event
    run_state["permit_wait"] = asyncio.Event()
    from .render import sync_run_state_ui
    from .terminal import layout_terminal

    sync_run_state_ui(runner, run_state)
    layout = layout_terminal.get()
    if layout is not None:
        layout.invalidate()
    try:
        await run_state["permit_wait"].wait()
    finally:
        run_state.pop("permit", None)
        wait = run_state.pop("permit_wait", None)
        if wait is not None and not wait.is_set():
            wait.set()
        sync_run_state_ui(runner, run_state)
        layout = layout_terminal.get()
        if layout is not None:
            layout.invalidate()

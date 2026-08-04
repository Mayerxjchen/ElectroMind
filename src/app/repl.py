from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import replace
from datetime import datetime

from prompt_toolkit.formatted_text import ANSI

from electromind import DeepSeek, Runner

from .clean import clean_electromind, format_clean_report
from .config import (
    ReplConfig,
    refresh_provider_from_disk,
)
from .exitcodes import EXIT_EXECUTION
from .render import (
    BLUE,
    DIM,
    RED,
    RESET,
    c,
    format_banner,
    print_command_header,
    print_command_result,
)
from .terminal import emit, emit_prompt
from .tool_permit import build_app_tool_hooks

# Module-level signal: set by /resume handler, consumed by REPL loops
_pending_thread_switch: str | None = None

EXTRA_SYSTEM = (
    "你是 electromind，一名严谨的工程师。回答保持简洁、直接、准确；不要输出表情符号；"
    "不要使用寒暄、口号或不必要的解释。"
    "\n\n"
    "目录区分："
    "\n- 用户的项目目录（host_root）是界面右侧展示的文件夹，用 list_host_files 查看。"
    "\n- 沙箱工作区（workspace）是临时的执行环境，用 list_dir 查看。"
    "\n- 当用户说「当前目录」「项目目录」「右侧目录」「我的文件」「绑定目录」时，默认指 host_root。"
)


def emit_user_line(text: str, *, color: bool, user_label: str) -> None:
    """Print a user line in the REPL (blocking mode)."""
    emit(c(f"{user_label}> {text}", on=color) if color else f"{user_label}> {text}")


def read_prompt_line(*, color: bool, user_label: str = "you") -> str:
    message = ANSI(f"{BLUE}{user_label}> {RESET}") if color else f"{user_label}> "
    return emit_prompt(message)


async def open_runner(config: ReplConfig) -> Runner:
    from electromind.execution import (
        ContainerRuntimeUnavailableError,
        ExecutionResolutionError,
        resolve_execution,
    )

    # Desktop / VS Code 可能在 wire 已启动后再写入 API Key；打开会话前从磁盘刷新。
    config = refresh_provider_from_disk(config)
    api_key = config.resolved_api_key()
    if not api_key:
        raise SystemExit(
            "需要 API Key：运行交互式 electromind 完成 setup，"
            "或写入 ~/.electromind/config.toml，或 export DEEPSEEK_API_KEY"
        )

    # 执行模式解析——单一能力决策入口
    ssh_config = (
        {
            "host": config.ssh_host,
            "config": config.ssh_config,
            "workdir": config.ssh_workdir,
        }
        if config.execution_mode == "ssh"
        else None
    )
    try:
        execution = resolve_execution(
            config.execution_mode,
            sandbox_backend=config.backend
            if config.execution_mode == "sandbox"
            else None,
            ssh_config=ssh_config,
            legacy_backend=config.backend if not config.execution_mode else None,
            legacy_command_policy=config.command_policy
            if not config.execution_mode
            else None,
        )
    except ContainerRuntimeUnavailableError as exc:
        raise SystemExit(str(exc)) from exc
    except ExecutionResolutionError as exc:
        raise SystemExit(str(exc)) from exc

    # 将解析结果映射到 config.backend，确保 Runner 创建正确的后端
    config = replace(config, backend=execution.resolved_backend)

    thread_id = config.thread_id or f"thread-{datetime.now():%Y%m%d-%H%M%S}"
    provider_kwargs = {"apikey": api_key}
    if config.provider_base_url:
        provider_kwargs["base_url"] = config.provider_base_url
    provider = DeepSeek(config.resolved_model(), **provider_kwargs)

    runner = await Runner.create(
        thread_id,
        provider,
        overrides=config.thread_overrides(),
        extra_system=EXTRA_SYSTEM,
        max_turns=config.resolved_max_turns(),
        tool_hooks=build_app_tool_hooks(
            auto=config.permission_auto(), auto_safe=config.permission_auto_safe()
        ),
    )
    # 将执行解析结果挂到 runner 上，供 CLI、Wire 和验证读取
    runner._execution = execution

    # 安全验证：实际 backend 与解析结果一致（自动解包 BackendGuard）
    from electromind.sandbox import backend_type_name

    actual = backend_type_name(runner.sandbox.backend)
    if actual != execution.resolved_backend:
        try:
            await runner.close()
        except Exception:
            pass
        raise SystemExit(
            f"执行后端不匹配：解析为 {execution.resolved_backend}，"
            f"实际创建了 {actual}。拒绝继续。"
        )

    return runner


def _frozen_notice(command: str) -> None:
    emit(f"{command} 设置已冻结在当前 thread；/new 或重启后生效")


def format_status_summary(runner: Runner, *, app=None, config=None) -> str:
    from electromind.sandbox import backend_type_name

    spec = runner.thread.spec
    backend = backend_type_name(runner.sandbox.backend)
    model = spec.model or "deepseek-v4-flash"
    mode = _spec_session_mode(runner)
    permission = (
        app.reducer.status.permission
        if app is not None
        else ((config.resolved_permission_mode() if config else "prompt") or "prompt")
    )
    project = str(runner.thread.project_path) if runner.thread.project_path else "—"
    context = _context_pct(runner)
    lines = [
        f"thread:     {runner.thread.id}",
        f"mode:       {mode}",
        f"target:     {backend}",
        f"permission: {permission}",
        f"model:      {model}",
        f"project:    {project}",
        f"workdir:    {runner.sandbox.workdir}",
        f"turns:      {sum(1 for m in runner.messages.data if m.role == 'user')}",
    ]
    if context is not None:
        lines.append(f"context:    ~{context}%")
    return "\n".join(lines)


def format_config_summary(config) -> str:
    if config is None:
        return "(config 未传入；运行 /config 需要交互入口提供配置)"
    return "\n".join(
        [
            f"model:           {config.resolved_model()}",
            f"mode:            {config.session_mode or 'run'}",
            f"target:          {config.execution_mode or 'sandbox'}",
            f"permission:      {config.resolved_permission_mode()}",
            f"max_turns:       {config.resolved_max_turns()}",
            f"project:         {config.project_path or os.getcwd()}",
            f"agent_tools:     {', '.join(config.resolved_agent_tools())}",
        ]
    )


def _context_pct(runner: Runner) -> int | None:
    try:
        from .tui.application import _context_pct as _compute

        return _compute(runner, runner.thread.spec.model or "deepseek-v4-flash")
    except Exception:
        return None


def split_prefixed_command(line: str) -> tuple[str, str] | None:
    """``!command`` → 当前 Execution Target 执行；``!!`` 为兼容别名。

    隐式语义已删除：不再区分 !→host / !!→sandbox。所有 ``!`` 命令都经
    ``runner.sandbox.commands.run``（policy + mode_guard + audit 的权限生命周期），
    REPL 不再直接 create_subprocess_exec。
    """
    if line.startswith("!!"):
        return ("target", line[2:].strip())
    if line.startswith("!"):
        return ("target", line[1:].strip())
    return None


async def run_prefixed_command(
    command: str,
    runner: Runner,
    *,
    color: bool,
    app=None,
) -> None:
    if app is not None:
        await app.run_shell_command(command)
        return
    # 阻塞 REPL：同一条权限生命周期（commands.run），只是行式展示
    from electromind.sandbox import backend_type_name

    target = backend_type_name(runner.sandbox.backend)
    print_command_header(target, command, color=color)
    result = await runner.sandbox.commands.run(command)
    print_command_result(result.stdout, result.stderr, result.exit_code, color=color)


async def handle_prefixed_command(
    line: str,
    runner: Runner,
    *,
    color: bool,
    app=None,
) -> bool:
    parsed = split_prefixed_command(line)
    if parsed is None:
        return False

    _target, command = parsed
    if not command:
        emit(c("empty command", RED, on=color))
        return True

    await run_prefixed_command(command, runner, color=color, app=app)
    return True


# slash 命令清单（TUI / 阻塞 REPL 共用；wire 的桌面菜单保持自己的清单）
SLASH_COMMANDS: list[tuple[str, str]] = [
    ("help", "列出所有可用的 slash 命令"),
    ("status", "当前模式 / 目标 / 权限 / 模型 / 上下文"),
    ("model", "当前模型（设置冻结于 thread，/new 生效）"),
    ("mode", "当前任务模式 ask | plan | run"),
    ("target", "当前执行目标 sandbox | local | ssh"),
    ("permissions", "当前权限模式与受审批工具"),
    ("config", "已解析配置摘要"),
    ("skills", "已加载的技能及其描述"),
    ("sessions", "列出所有历史会话"),
    ("resume", "切换会话（无参数列出，指定 ID 直接切换）"),
    ("new", "新建会话"),
    ("clear", "清空时间线（TUI）"),
    ("compact", "报告上下文用量（压缩暂不支持）"),
    ("history", "当前会话的消息概览"),
    ("doctor", "环境诊断"),
    ("tasks", "当前 Run 状态与排队输入"),
    ("files", "浏览项目文件（Enter 插入路径）"),
    ("exit", "退出"),
]


def format_slash_help() -> str:
    width = max(len(name) for name, _ in SLASH_COMMANDS)
    return "\n".join(f"/{name:<{width}}  {summary}" for name, summary in SLASH_COMMANDS)


def _spec_session_mode(runner: Runner) -> str:
    value = runner.thread.spec.session_mode or "agent"
    return "run" if value == "agent" else value


async def handle_command(
    cmd: str,
    runner: Runner,
    *,
    color: bool,
    app=None,
    config=None,
) -> bool:
    global _pending_thread_switch
    del color
    if cmd in ("/exit", "/quit"):
        return True
    if cmd == "/help":
        if app is not None:
            app.open_help()  # TUI：Help overlay（Esc 关闭）
            return False
        emit(format_slash_help())
        return False
    if cmd == "/status":
        emit(format_status_summary(runner, app=app, config=config))
        return False
    if cmd == "/model":
        if app is not None:
            app.open_model_selector()  # TUI：候选模型选择器
            return False
        emit(f"model: {runner.thread.spec.model or 'deepseek-v4-flash'}")
        _frozen_notice(cmd)
        return False
    if cmd.startswith("/model "):
        _frozen_notice("/model")
        return False
    if cmd == "/mode":
        emit(f"mode: {_spec_session_mode(runner)}")
        return False
    if cmd.startswith("/mode "):
        _frozen_notice("/mode")
        return False
    if cmd == "/target":
        if app is not None:
            app.open_target_selector()  # TUI：目标选择器
            return False
        from electromind.sandbox import backend_type_name

        emit(f"target: {backend_type_name(runner.sandbox.backend)}")
        return False
    if cmd.startswith("/target "):
        _frozen_notice("/target")
        return False
    if cmd == "/files":
        if app is not None:
            app.open_file_picker()
            return False
        emit("文件浏览仅在 TUI 模式支持")
        return False
    if cmd == "/permissions":
        mode = (
            app.reducer.status.permission
            if app is not None
            else (
                (config.resolved_permission_mode() if config else "prompt") or "prompt"
            )
        )
        emit(f"permission-mode: {mode}")
        emit("受审批工具: run_command, copy_from_host")
        return False
    if cmd == "/config":
        emit(format_config_summary(config))
        return False
    if cmd == "/new":
        from datetime import datetime

        _pending_thread_switch = f"thread-{datetime.now():%Y%m%d-%H%M%S}"
        return True
    if cmd == "/clear":
        if app is not None:
            app.clear_timeline()
        else:
            emit("清屏仅在 TUI 模式支持")
        return False
    if cmd == "/compact":
        # 真压缩：保留系统消息 + 最近 N 条消息，更早的丢弃并落盘。
        # 模型只看到最近上下文；TUI 时间线同步清空旧条目。
        keep = 12
        messages = runner.messages.data
        if len(messages) > keep + 1:
            kept = messages[:1] + messages[-keep:]
            runner.messages.data = kept
            flush = getattr(runner, "flush_conversation", None)
            if callable(flush):
                flush()
            if app is not None:
                app.clear_timeline()
                app.notice(f"已压缩：{len(messages)} → {len(kept)} 条消息")
            else:
                emit(f"已压缩：{len(messages)} → {len(kept)} 条消息")
        else:
            pct = _context_pct(runner)
            suffix = f"（{pct}%）" if pct is not None else ""
            emit(f"无需压缩{suffix}：当前 {len(messages)} 条消息")
        return False
    if cmd == "/tasks":
        state = runner.run_state
        app_pending = len(app.pending_inputs) if app is not None else 0
        emit(
            f"run: phase={state.phase} turn={state.turn} stop={state.stop_reason or '—'}"
            f" · 排队输入: {app_pending}"
        )
        return False
    if cmd == "/doctor":
        from .commands.doctor import collect_checks

        for check in collect_checks().checks:
            mark = "ok" if check.ok else "FAIL"
            emit(f"[{mark}] {check.name}: {check.detail}")
        return False
    if cmd == "/pwd":
        emit(runner.sandbox.workdir)
        return False
    if cmd == "/ls":
        entries = await runner.sandbox.files.list(runner.sandbox.home)
        for entry in entries:
            tag = "d" if entry.is_dir else "f"
            emit(f"  {tag} {entry.name}")
        return False
    if cmd == "/skills":
        if not runner.skills.names():
            emit("(no skills loaded)")
            return False
        for skill in runner.skills.list():
            emit(f"  {skill.name}: {skill.description}")
        return False
    if cmd == "/history":
        for message in runner.messages.data:
            preview = str(message.content)[:80].replace("\n", " ")
            emit(f"  [{message.role}] {preview}")
        return False
    if cmd == "/sessions":
        from .sessions import format_session_table, list_sessions

        emit(format_session_table(list_sessions()))
        return False
    if cmd.startswith("/resume"):
        from .sessions import (
            find_session_by_id,
            list_sessions,
        )

        parts = cmd.split(maxsplit=1)

        # /resume <thread_id>
        if len(parts) > 1 and parts[1].strip():
            target = find_session_by_id(parts[1].strip())
            if target is None:
                # Try numeric index
                try:
                    idx = int(parts[1].strip()) - 1
                    sessions = list_sessions()
                    if 0 <= idx < len(sessions):
                        target = sessions[idx]
                except ValueError:
                    pass
            if target is None:
                emit(f"会话不存在: {parts[1].strip()}")
                return False
            chosen_id = target.id

        # /resume without arguments → 会话选择器
        elif len(parts) == 1 and cmd.startswith("/resume"):
            if app is not None:
                # TUI：overlay 选择器（复用 slash popup 的模糊搜索），
                # 避免与 prompt_toolkit 抢终端（旧 termios picker 仅阻塞模式用）
                app.open_session_picker()
                return False
            from .sessions import interactive_session_picker

            sessions = list_sessions()
            if not sessions:
                emit("没有可恢复的会话")
                return False
            chosen_id = await asyncio.to_thread(
                interactive_session_picker,
                sessions,
                current_id=runner.thread.id,
            )
            if chosen_id is None:
                return False
        else:
            return False

        _pending_thread_switch = chosen_id
        emit(f"正在切换到: {chosen_id}")
        return True  # signal REPL loop to restart with new thread
    emit(f"unknown command: {cmd}")
    return False


async def prompt(color: bool, *, user_label: str = "you") -> str | None:
    try:
        return await asyncio.to_thread(
            read_prompt_line, color=color, user_label=user_label
        )
    except (EOFError, KeyboardInterrupt):
        return None


def say_goodbye(*, color: bool) -> None:
    emit(c("bye", DIM, on=color), flush=True)


def format_fatal_error(exc: BaseException, *, phase: str) -> str:
    """Human-readable fatal error; keep traceback out of the REPL by default."""
    label = "关闭" if phase == "close" else "启动"
    name = type(exc).__name__
    module = type(exc).__module__ or ""
    text = str(exc).strip() or name
    if (
        "asyncssh" in module
        or name.startswith("SFTP")
        or name
        in {"DisconnectError", "ConnectionLost", "ConnectionError", "TimeoutError"}
        or "ssh" in text.lower()
        and ("connect" in text.lower() or "timed out" in text.lower())
    ):
        hint = (
            "请检查 SSH 别名、网络、密钥，以及远端 workdir 是否可写。"
            if phase == "start"
            else "SSH 连接可能已断开。"
        )
        return f"electromind {label}失败（SSH 沙箱）: {text}\n  {hint}"
    lowered = text.lower()
    if "docker" in lowered or "podman" in lowered:
        return (
            f"electromind {label}失败（容器沙箱）: {text}\n"
            "  请确认 Docker/Podman 已启动，且镜像已构建。"
        )
    if isinstance(exc, (FileNotFoundError, KeyError, ValueError)):
        return f"electromind {label}失败: {text}"
    if isinstance(exc, OSError):
        return f"electromind {label}失败: {text}"
    return f"electromind {label}失败: {name}: {text}"


async def run_blocking_repl(
    config: ReplConfig,
    *,
    color: bool | None = None,
    initial_prompt: str | None = None,
    no_session_persistence: bool = False,
) -> int:
    """阻塞 REPL（非 TTY / --blocking）：经 EmbeddedAgentClient 走 Harness 生命周期。

    验收 G-1：不再直接持有 Runner 作为状态源——输入走 client.send_input，
    事件流经 client 渲染，审批经 client.resolve_approval（绑定 thread+run）。
    """
    global _pending_thread_switch
    use_color = sys.stdout.isatty() if color is None else color
    from datetime import datetime

    from .client import EmbeddedAgentClient
    from .render import RenderState

    thread_id = config.thread_id or f"thread-{datetime.now():%Y%m%d-%H%M%S}"
    state = RenderState(
        color=use_color,
        user_label=config.resolved_user_label(),
        assistant_label=config.resolved_assistant_label(),
        persist_meta=not no_session_persistence,
    )
    done = asyncio.Event()
    clients: list = []  # 所有存活 client（进程退出时统一关闭）

    async def runner_factory(tid: str) -> Runner:
        return await open_runner(replace(config, thread_id=tid))

    sink = _blocking_sink(state, done, config, thread_id, use_color, runner_factory)
    client = EmbeddedAgentClient(
        runner_factory,
        config=config,
        event_sink=sink,
        persist_meta=not no_session_persistence,
    )
    sink.attach_client(client)
    clients.append(client)

    exit_code = 0
    had_user_turn = False
    try:
        # 打开初始 Runner（banner / slash 命令需要），灌入历史不重复渲染
        runner = await client.get_runner(thread_id)
        emit(format_banner(runner, color=use_color), flush=True)

        if initial_prompt:
            await _blocking_send(
                client,
                done,
                thread_id,
                config,
                initial_prompt,
                use_color,
                state,
            )
            had_user_turn = True

        while True:
            line = await prompt(use_color, user_label=config.resolved_user_label())
            if line is None:
                emit()
                say_goodbye(color=use_color)
                break
            line = line.strip()
            if not line:
                continue
            runner = client.runner(thread_id) or await client.get_runner(thread_id)

            if await handle_prefixed_command(line, runner, color=use_color):
                continue
            if line.startswith("/"):
                cmd_name = line.split()[0] if line.strip() else ""
                known = {f"/{name}" for name, _ in SLASH_COMMANDS} | {"/quit"}
                is_known = cmd_name in known or cmd_name.startswith("/resume")
                if is_known:
                    exit_requested = await handle_command(
                        line, runner, color=use_color, config=config
                    )
                    if _pending_thread_switch:
                        new_thread_id = _pending_thread_switch
                        _pending_thread_switch = None
                        config = replace(config, thread_id=new_thread_id)
                        # 旧 client 保持存活（后台 Run 继续，事件不再渲染、
                        # 不触碰新 done）；每个 client 拥有独立 done。
                        if hasattr(sink, "active"):
                            sink.active = False
                        done = asyncio.Event()
                        thread_id = new_thread_id  # 局部 thread_id 更新
                        sink = _blocking_sink(
                            state,
                            done,
                            config,
                            new_thread_id,
                            use_color,
                            runner_factory,
                        )
                        sink.active = True
                        client = EmbeddedAgentClient(
                            runner_factory,
                            config=config,
                            event_sink=sink,
                            persist_meta=not no_session_persistence,
                        )
                        sink.attach_client(client)
                        clients.append(client)
                        runner = await client.get_runner(new_thread_id)
                        emit(format_banner(runner, color=use_color), flush=True)
                        continue
                    if exit_requested:
                        say_goodbye(color=use_color)
                        break
                    continue
            try:
                await _blocking_send(
                    client, done, thread_id, config, line, use_color, state
                )
                had_user_turn = True
            except KeyboardInterrupt:
                emit()
                say_goodbye(color=use_color)
                break
    except BaseException as exc:
        if isinstance(exc, SystemExit):
            raise
        if isinstance(exc, KeyboardInterrupt):
            emit()
            say_goodbye(color=use_color)
        else:
            message = format_fatal_error(exc, phase="start")
            emit(c(message, RED, on=use_color), file=sys.stderr, flush=True)
            exit_code = EXIT_EXECUTION
    finally:
        for stale in clients:
            try:
                await stale.close()
            except BaseException:
                pass
        keep = {thread_id} if had_user_turn else set()
        report = clean_electromind(keep_thread_ids=keep)
        clean_message = format_clean_report(report)
        if clean_message:
            emit(c(clean_message, DIM, on=use_color), flush=True)
    return exit_code


def _blocking_sink(state, done, config, thread_id, use_color, runner_factory):
    """阻塞 REPL 的事件接收器：协议事件 → RenderState 流式渲染 + 审批。"""
    from electromind import ReasoningDelta, TextDelta, ToolCallBegin, ToolResult

    from .render import DIM, YELLOW, render_event
    from .render import c as _c
    from .terminal import emit, emit_prompt
    from .tool_permit import parse_permit_answer

    client_holder = {"client": None}

    def handle(line: dict) -> None:
        method = line.get("method", "")
        params = line.get("params", {}) or {}
        if method == "item/delta":
            kind = params.get("kind")
            text = str(params.get("text", ""))
            if kind == "text":
                render_event(TextDelta(text), state)
            elif kind == "reasoning":
                render_event(ReasoningDelta(text), state)
        elif method == "item/started" and params.get("kind") == "tool":
            render_event(
                ToolCallBegin(
                    str(params.get("tool_call_id", "")),
                    str(params.get("name", "")),
                    str(params.get("arguments", "")),
                ),
                state,
            )
        elif method == "item/completed" and params.get("kind") == "tool":
            render_event(
                ToolResult(
                    str(params.get("tool_call_id", "")),
                    str(params.get("name", "")),
                    str(params.get("content", "")),
                    ok=bool(params.get("ok", False)),
                ),
                state,
            )
        elif method == "approval/requested":
            # 阻塞模式：逐次 y/N 审批（经 client.resolve_approval 绑定 thread+run）
            asyncio.create_task(
                _blocking_approval(
                    client_holder,
                    params,
                    emit,
                    emit_prompt,
                    parse_permit_answer,
                    _c,
                    YELLOW,
                    DIM,
                )
            )
        elif method == "run/completed":
            state.finish()
            done.set()

    def attach_client(client):
        """同步挂载：审批到达时 client_holder 立即可用（复验 P0-4）。"""
        client_holder["client"] = client

    handle.attach_client = attach_client  # type: ignore[attr-defined]
    return handle


async def _blocking_approval(
    client_holder, params, emit, emit_prompt, parse_permit_answer, c, YELLOW, DIM
) -> None:
    client = client_holder["client"]
    if client is None:
        return
    emit(
        c(
            f"审批 {params.get('name', '')}：{params.get('summary', '')} [y/N]",
            YELLOW,
            on=True,
        )
    )
    while True:
        line = await asyncio.to_thread(emit_prompt, "permit> ")
        answer = parse_permit_answer(line)
        if answer is None:
            emit(c("输入 y 批准 / n 拒绝", DIM, on=True))
            continue
        await client.resolve_approval(
            str(params.get("thread_id", "")),
            str(params.get("run_id", "")),
            str(params.get("approval_id", "")),
            answer,
            tool_call_id=str(params.get("tool_call_id", "")),
        )
        return


async def _blocking_send(
    client, done, thread_id, config, text, use_color, state
) -> None:
    """发送一条输入并等待 Run 完成（阻塞 REPL 的回合边界）。"""
    from electromind.harness.identity import new_request_id

    del use_color, state
    done.clear()
    try:
        await client.send_input(
            thread_id,
            text,
            delivery="auto",
            request_id=new_request_id(),
            mode=config.session_mode or "run",
        )
    except Exception as exc:
        from .render import RED
        from .render import c as _c
        from .terminal import emit as _emit

        _emit(
            _c(f"发送失败: {type(exc).__name__}: {exc}", RED, on=False), file=sys.stderr
        )
        return
    await done.wait()


async def run_repl(
    config: ReplConfig,
    *,
    color: bool | None = None,
    initial_prompt: str | None = None,
    no_session_persistence: bool = False,
) -> int:
    """TTY 默认底栏固定输入；管道/重定向或 ``--blocking`` 用阻塞模式。"""
    if sys.stdout.isatty() and not config.blocking:
        from .concurrent_repl import run_concurrent_repl

        return await run_concurrent_repl(
            config,
            color=color,
            initial_prompt=initial_prompt,
            no_session_persistence=no_session_persistence,
        )
    return await run_blocking_repl(
        config,
        color=color,
        initial_prompt=initial_prompt,
        no_session_persistence=no_session_persistence,
    )


def main(argv: list[str] | None = None) -> None:
    """兼容入口：统一走 app.cli 分派（保留给旧脚本/测试）。"""
    from .cli import main as cli_main

    cli_main(argv)

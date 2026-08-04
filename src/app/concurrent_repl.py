"""底栏固定输入 REPL — 客户端驱动的多 Thread 语义化 TUI（CLI-4）。

管线：Composer → EmbeddedAgentClient（Harness 生命周期）→ 事件流 → CliApp 视图。
/resume、/new 只切换视图，不关闭旧 Runner；后台 Thread 的 Run 继续执行。
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import replace
from datetime import datetime

from electromind import Runner

from .client import EmbeddedAgentClient
from .config import ReplConfig
from .exitcodes import EXIT_EXECUTION
from .render import DIM, RED, c
from .repl import (
    format_fatal_error,
    handle_command,
    handle_prefixed_command,
    open_runner,
    say_goodbye,
)
from .terminal import emit, layout_terminal
from .tui.application import CliApp


class NoticeSink:
    """terminal.emit() 的 TUI 适配器：slash 命令输出进入当前视图 Notice。"""

    def __init__(self, app: CliApp) -> None:
        self.app = app

    def write(self, text: str = "", *, end: str = "\n") -> None:
        del end
        if text:
            self.app.notice(text.rstrip())

    def invalidate(self) -> None:
        self.app.invalidate()


def build_slash_entries(app: CliApp, runner: Runner) -> list[tuple[str, str]]:
    from .repl import SLASH_COMMANDS

    entries = list(SLASH_COMMANDS)
    for skill in runner.skills.list():
        entries.append((skill.name, skill.description))
    return entries


async def run_tui_loop(
    app: CliApp,
    client: EmbeddedAgentClient,
    config: ReplConfig,
) -> bool:
    """输入编排：Enter=发送/steer，Tab=排队；/ 与 ! 命令走当前视图 Runner。"""
    input_task = asyncio.create_task(app.input_queue.get())
    had_user_turn = False

    try:
        while True:
            done, _ = await asyncio.wait(
                {input_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if input_task not in done:
                continue

            try:
                line = input_task.result()
            except asyncio.CancelledError:
                break

            input_task = asyncio.create_task(app.input_queue.get())

            if line is None:
                break

            text = line.strip()
            if not text:
                continue

            # 当前视图 Runner（/resume、/new 后已由 switch_thread 保证存在）
            runner = client.runner(app.thread_id)

            if text.startswith("!"):
                await handle_prefixed_command(text, runner, color=app.color, app=app)
                continue

            if text.startswith("/"):
                if app.state == "running":
                    app.notice("run 进行中，/ 命令请等结束后再用")
                    continue
                exit_requested = await handle_command(
                    text,
                    runner,
                    color=app.color,
                    app=app,
                    config=config,
                )
                if exit_requested:
                    break
                continue

            if app.state == "running":
                app.send_turn(text, delivery="immediate")
                had_user_turn = True
                continue

            app.send_turn(text, delivery="auto")
            had_user_turn = True
    finally:
        if not input_task.done():
            input_task.cancel()
    return had_user_turn


async def run_concurrent_repl(
    config: ReplConfig,
    *,
    color: bool | None = None,
    initial_prompt: str | None = None,
    no_session_persistence: bool = False,
) -> int:
    from .tui.capabilities import color_supported, fullscreen_supported

    use_color = color_supported(explicit=color)
    if not sys.stdout.isatty():
        from .repl import run_blocking_repl

        return await run_blocking_repl(
            config,
            color=use_color,
            initial_prompt=initial_prompt,
            no_session_persistence=no_session_persistence,
        )

    # R6：不支持 full-screen（TERM=dumb 等）→ 自动降级 inline（保留 scrollback）
    inline = config.inline or not fullscreen_supported()
    if inline:
        print(
            "终端不支持 alternate screen（TERM=%s），降级为 inline 模式。"
            % (__import__("os").environ.get("TERM") or "unset"),
            file=sys.stderr,
        )

    from . import repl as repl_module
    from .clean import clean_electromind, format_clean_report

    exit_code = 0
    had_user_turn = False
    client: EmbeddedAgentClient | None = None
    try:
        thread_id = config.thread_id or f"thread-{datetime.now():%Y%m%d-%H%M%S}"

        async def runner_factory(tid: str) -> Runner:
            return await open_runner(replace(config, thread_id=tid))

        app = CliApp(
            color=use_color,
            mode=_session_mode(config),
            target=config.execution_mode or "sandbox",
            permission=config.resolved_permission_mode(),
            model=config.resolved_model(),
            project=config.project_path or "",
            thread_id=thread_id,
            full_screen=not inline,
        )
        client = EmbeddedAgentClient(
            runner_factory, config=config, event_sink=app.handle_event
        )
        app.client = client

        # 初始 Thread：打开 Runner、灌入历史、展示紧凑启动头
        runner = await client.get_runner(thread_id)
        await app.switch_thread(thread_id)
        app.set_slash_entries(build_slash_entries(app, runner))
        app.show_header()
        # Local 目标必须显式选择并展示风险（resolve_execution 的 warning）
        execution = getattr(runner, "_execution", None)
        if execution is not None and getattr(execution, "warning", None):
            app.notice(execution.warning.splitlines()[0])
        if initial_prompt:
            app.input_queue.put_nowait(initial_prompt)

        while True:
            pt_app = app.build()
            token = layout_terminal.set(NoticeSink(app))
            try:
                app_task = asyncio.create_task(pt_app.run_async())
                loop_task = asyncio.create_task(run_tui_loop(app, client, config))
                had_user_turn = await loop_task
                app.notice("bye")
                pt_app.exit()
                await app_task
            finally:
                layout_terminal.reset(token)

            # /resume、/new：只切换视图 —— 旧 Runner 与后台 Run 保持运行
            if repl_module._pending_thread_switch:
                new_thread_id = repl_module._pending_thread_switch
                repl_module._pending_thread_switch = None
                await app.switch_thread(new_thread_id)
                runner = client.runner(new_thread_id)
                if runner is not None:
                    app.set_slash_entries(build_slash_entries(app, runner))
                app.notice(f"已切换到: {new_thread_id}")
                continue
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
        if client is not None:
            try:
                await client.close()  # 关闭所有 Thread 的 Runner
            except BaseException:
                pass
        if client is not None:
            report = clean_electromind(
                keep_thread_ids=set(client.thread_ids) if had_user_turn else set()
            )
            clean_message = format_clean_report(report)
            if clean_message:
                emit(c(clean_message, DIM, on=use_color), flush=True)
    return exit_code


def _session_mode(config: ReplConfig) -> str:
    return config.session_mode or "run"


def main(argv: list[str] | None = None) -> None:
    from .cli_parser import build_parser
    from .config import config_from_args

    parser = build_parser()
    config = config_from_args(parser.parse_args(argv))
    try:
        code = asyncio.run(run_concurrent_repl(config))
    except KeyboardInterrupt:
        emit()
        raise SystemExit(0) from None
    raise SystemExit(code)


__all__ = ["run_concurrent_repl", "main", "NoticeSink", "EmbeddedAgentClient"]

"""底栏固定输入 REPL — 全屏布局，输入行钉在终端视口最底。"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import replace

from electromind import Runner

from .config import ReplConfig
from .layout_terminal import LayoutTerminal
from .render import (
    DIM,
    RED,
    YELLOW,
    RenderState,
    c,
    consume_run,
    emit_user_line,
    format_banner,
    sync_run_state_ui,
)
from .repl import (
    format_fatal_error,
    handle_command,
    handle_prefixed_command,
    open_runner,
    say_goodbye,
)
from .terminal import emit, layout_terminal
from .tool_permit import apply_permit_answer, parse_permit_answer


async def dispatch_user_line(
    line: str,
    *,
    runner: Runner,
    run_task: asyncio.Task | None,
    color: bool,
) -> tuple[str, asyncio.Task | None]:
    """单元测试用：steer 分支。"""
    text = line.strip()
    if not text:
        return "continue", run_task
    if run_task is not None and not run_task.done():
        runner.steer(text)
        emit(c(f"↳ steer: {text}", DIM, on=color))
        return "continue", run_task
    return "start_run", run_task


async def run_layout_loop(
    runner: Runner,
    terminal: LayoutTerminal,
    run_state: dict,
    *,
    color: bool,
    user_label: str,
    assistant_label: str,
    permit_auto: bool = False,
) -> bool:
    run_task: asyncio.Task | None = None
    had_user_turn = False
    input_task = asyncio.create_task(terminal.input_queue.get())
    terminal.set_prefix(f"{user_label}> ")

    while True:
        run_state["active"] = run_task is not None and not run_task.done()
        sync_run_state_ui(runner, run_state)
        terminal.invalidate()
        idle_prefix = f"{user_label}> "
        if run_state.get("permit") is not None:
            terminal.set_prefix("permit> ")
        elif run_state["active"]:
            terminal.set_prefix("steer> ")
        else:
            terminal.set_prefix(idle_prefix)

        wait_set: set[asyncio.Task] = {input_task}
        if run_state["active"] and run_task is not None:
            wait_set.add(run_task)

        done, _ = await asyncio.wait(
            wait_set,
            return_when=asyncio.FIRST_COMPLETED,
        )

        if run_task is not None and run_task in done:
            run_task.result()
            run_task = None
            had_user_turn = True
            if input_task.done():
                input_task = asyncio.create_task(terminal.input_queue.get())
            continue

        if input_task not in done:
            continue

        try:
            line = input_task.result()
        except asyncio.CancelledError:
            break

        input_task = asyncio.create_task(terminal.input_queue.get())

        if line is None:
            terminal.write()
            say_goodbye(color=color)
            break

        text = line.strip()
        if not text:
            continue

        if await handle_prefixed_command(text, runner, color=color):
            continue

        if text.startswith("/"):
            if run_task is not None and not run_task.done():
                emit(c("run 进行中，/ 命令请等结束后再用", YELLOW, on=color))
                continue
            if await handle_command(text, runner, color=color):
                say_goodbye(color=color)
                break
            continue

        permit_event = run_state.get("permit")
        if permit_event is not None:
            answer = parse_permit_answer(text)
            if answer is None:
                emit(c("输入 y 批准 / n 拒绝", DIM, on=color))
                continue
            apply_permit_answer(runner, permit_event.tool_call_id, answer)
            label = "已批准" if answer else "已拒绝"
            emit(c(label, DIM, on=color))
            wait = run_state.get("permit_wait")
            if wait is not None:
                wait.set()
            continue

        if run_task is not None and not run_task.done():
            runner.steer(text)
            emit(c(f"↳ steer: {text}", DIM, on=color))
            continue

        emit_user_line(text, color=color, user_label=user_label)
        state = RenderState(
            color=color,
            user_label=user_label,
            assistant_label=assistant_label,
        )
        run_task = asyncio.create_task(
            consume_run(
                runner,
                text,
                state,
                run_state=run_state,
                permit_auto=permit_auto,
            )
        )
        had_user_turn = True

    return had_user_turn


async def run_concurrent_repl(config: ReplConfig, *, color: bool | None = None) -> int:
    use_color = sys.stdout.isatty() if color is None else color
    if not sys.stdout.isatty():
        from .repl import run_blocking_repl

        return await run_blocking_repl(config, color=use_color)

    from .clean import clean_electromind, format_clean_report
    from . import repl as repl_module

    runner: Runner | None = None
    exit_code = 0
    had_user_turn = False
    try:
        runner = await open_runner(config)

        while True:
            run_state: dict = {"active": False, "permit": None, "status": "空闲"}
            sync_run_state_ui(runner, run_state)
            terminal = LayoutTerminal(color=use_color)
            app = terminal.build_application(run_state=run_state, runner=runner)

            token = layout_terminal.set(terminal)
            try:
                terminal.write(format_banner(runner, color=use_color))
                terminal.write(
                    c(
                        "输入行固定在最底；run 中 Enter=steer"
                        + ("" if config.permission_auto() else "，危险工具需 permit> 审批")
                        + "，Esc/Ctrl+C=cancel",
                        DIM,
                        on=use_color,
                    )
                )

                loop_task = asyncio.create_task(
                    run_layout_loop(
                        runner,
                        terminal,
                        run_state,
                        color=use_color,
                        user_label=config.resolved_user_label(),
                        assistant_label=config.resolved_assistant_label(),
                        permit_auto=config.permission_auto(),
                    )
                )
                app_task = asyncio.create_task(app.run_async())
                had_user_turn = await loop_task
                app.exit()
                await app_task
            finally:
                layout_terminal.reset(token)

            # Check for thread switch request from /resume
            if repl_module._pending_thread_switch:
                new_thread_id = repl_module._pending_thread_switch
                repl_module._pending_thread_switch = None
                config = replace(config, thread_id=new_thread_id)
                # Close old runner before opening new one
                if runner is not None:
                    try:
                        await runner.close()
                    except BaseException:
                        pass
                runner = await open_runner(config)
                terminal.write(c(f"已切换到: {new_thread_id}", DIM, on=use_color))
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
            exit_code = 1
    finally:
        if runner is not None:
            try:
                await runner.close()
            except BaseException as exc:
                if isinstance(exc, SystemExit):
                    raise
                if exit_code == 0:
                    message = format_fatal_error(exc, phase="close")
                    emit(c(message, RED, on=use_color), file=sys.stderr, flush=True)
                    exit_code = 1
            keep = {runner.thread.id} if had_user_turn else set()
            report = clean_electromind(keep_thread_ids=keep)
            clean_message = format_clean_report(report)
            if clean_message:
                emit(c(clean_message, DIM, on=use_color), flush=True)
    return exit_code


def main(argv: list[str] | None = None) -> None:
    from .repl import build_parser, config_from_args

    parser = build_parser()
    config = config_from_args(parser.parse_args(argv))
    try:
        code = asyncio.run(run_concurrent_repl(config))
    except KeyboardInterrupt:
        emit()
        raise SystemExit(0) from None
    raise SystemExit(code)

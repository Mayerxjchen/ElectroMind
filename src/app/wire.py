"""pagent --wire —— stdio NDJSON 后端，供外部前端（如 VS Code 插件）驱动 Agent。

三条流各司其职：

- **stdout**：每行一个事件（Wire 协议）。透传 ``runner.run(return_type="event")``
  产出的事件，用 ``pagentv4/adapters/acp.py`` 的 ``encode_event_line`` 序列化；
  需审批的工具再补一条 ``PermitRequest`` 控制事件；失败时发 ``Error`` 控制事件
  （前端撤 loading 并展示错误气泡）。
- **stdin**：每行一个 JSON 命令，驱动 Agent。
- **stderr**：诊断日志，与事件流分开，前端可单独展示。

入站命令（前端 → 本进程）::

    {"cmd": "user", "text": "..."}                跑一轮 Agent，事件流式写到 stdout
    {"cmd": "user", "text": "/skills"}            以 / 开头的走 slash 命令，不跑 Agent
    {"cmd": "commands"}                           请求可用 slash 命令清单（供前端菜单）
    {"cmd": "permit", "tool_call_id": "..."}      批准某次工具调用
    {"cmd": "deny", "tool_call_id": "...", "reason": "..."}  拒绝某次工具调用
    {"cmd": "reset"}                              结束当前会话、开一个干净 thread
    {"cmd": "resume", "thread_id": "..."}         切到已有 thread，回放其历史
    {"cmd": "list_threads"}                       列出当前 pagent home 下可恢复会话
    {"cmd": "cancel"}                             取消当前运行（并发取消属后续课程）

reset 与 resume 换 runner 后都补发一条 ``HistoryReplay`` 控制事件：空数组表示新会话
（前端清屏），非空则携带该 thread 的历史消息，前端逐条重建气泡/思考/工具卡。

slash 命令复用 REPL 的只读能力（技能列表、历史概览、沙箱目录等），结果通过
``SlashResult`` 控制事件回给前端渲染成一张命令卡；可用清单通过 ``SlashCommands``
事件下发，前端据此填充输入框旁的斜杠菜单（清单以本进程为准，避免前后端漂移）。


并发模型：一轮 Agent 作为后台 task 跑（``state["turn"]``），主循环不阻塞地继续读
stdin。这样工具审批（``run_command`` / ``copy_from_host``）在后端挂起等待时，前端仍能
把 permit/deny 命令送进来解开阻塞 —— 审批走 ``runner.inbound``，从主循环这一侧推入。
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import replace
from datetime import datetime

from pagentv4 import ToolCallBegin
from pagentv4.adapters.acp import encode_event_line
from pagentv4.core.message import TextChunk, ThinkingChunk, ToolCall, ToolResult
from pagentv4.paths import resolve_pagent_home
from pagentv4.runtime.thread import default_threads_root

from .clean import clean_pagent, format_clean_report, iter_thread_dirs
from .config import ReplConfig
from .repl import open_runner
from .tool_permit import needs_tool_permit, summarize_tool_args

# metainfo.json 里 title 的最大字符数：超出截断加省略号，供前端会话列表展示。
TITLE_MAX_CHARS = 40


def log(text: str) -> None:
    """诊断日志写 stderr，避免污染 stdout 的事件流。"""
    print(text, file=sys.stderr, flush=True)


def emit_line(line: str) -> None:
    """把一行事件写到 stdout。line 已自带换行（encode_event_line 的约定）。"""
    sys.stdout.write(line)
    sys.stdout.flush()


def parse_command(line: str) -> dict | None:
    """解析一行 stdin 命令；非法 JSON 或非对象只记日志并丢弃。"""
    try:
        command = json.loads(line)
    except json.JSONDecodeError:
        log(f"[wire] skip non-json line: {line!r}")
        return None
    if not isinstance(command, dict):
        log(f"[wire] skip non-object command: {line!r}")
        return None
    return command


def emit_permit_request(event: ToolCallBegin) -> None:
    """需审批的工具：在 ToolCallBegin 之后补发一条审批请求，让前端弹批准/拒绝。

    这不是 core Event，而是 wire 层的控制事件，仍套用 JSON-RPC notification 形状，
    前端按 tool_call_id 把它挂到对应的工具卡片上。
    """
    payload = {
        "jsonrpc": "2.0",
        "method": "PermitRequest",
        "params": {
            "tool_call_id": event.tool_call_id,
            "name": event.name,
            "summary": summarize_tool_args(event.name, event.arguments),
        },
    }
    emit_line(json.dumps(payload, ensure_ascii=False) + "\n")


def history_messages(runner) -> list[dict]:
    """把 runner.messages 规整成前端易渲染的简单数组，供 HistoryReplay 回放。

    每个 Message 存一个 content chunk（流式 text/thinking 已在存储层合并成一行），
    这里按 chunk 类型摊平成扁平记录，字段与前端渲染一一对应：

    - text/thinking：``{"kind": ..., "role": ..., "text": ...}``
    - 工具调用：``{"kind": "tool_call", "tool_call_id", "name", "arguments"}``
    - 工具结果：``{"kind": "tool_result", "tool_call_id", "content"}``

    system 消息不回放（前端不展示系统提示）。
    """
    out: list[dict] = []
    for message in runner.messages.data:
        content = message.content
        if isinstance(content, TextChunk):
            if message.role == "system":
                continue
            out.append({"kind": "text", "role": message.role, "text": content.text})
        elif isinstance(content, ThinkingChunk):
            out.append({"kind": "thinking", "role": message.role, "text": content.text})
        elif isinstance(content, ToolCall):
            out.append(
                {
                    "kind": "tool_call",
                    "tool_call_id": content.id,
                    "name": content.name,
                    "arguments": content.arguments,
                }
            )
        elif isinstance(content, ToolResult):
            out.append(
                {
                    "kind": "tool_result",
                    "tool_call_id": content.tool_call_id,
                    "content": content.text,
                }
            )
    return out


def emit_history_replay(runner) -> None:
    """补发一条 HistoryReplay 控制事件，让前端重建会话视图。

    空数组表示新会话（前端清屏）；非空则前端逐条回放成气泡/思考/工具卡。
    与 PermitRequest 一样是 wire 层控制事件，套 JSON-RPC notification 形状。
    metainfo 里的 title 一并带上，前端据此在标题栏/列表展示面向用户的名字。
    """
    payload = {
        "jsonrpc": "2.0",
        "method": "HistoryReplay",
        "params": {
            "thread_id": runner.thread.id,
            "title": runner.thread.load_metainfo().get("title", ""),
            "messages": history_messages(runner),
        },
    }
    emit_line(json.dumps(payload, ensure_ascii=False) + "\n")


def list_thread_entries() -> list[dict[str, str]]:
    """按当前 cwd 解析的 pagent home 列出可恢复 thread（与落盘同一判定）。"""
    entries: list[dict[str, str]] = []
    for thread_dir in sorted(
        iter_thread_dirs(default_threads_root()),
        key=lambda path: path.name,
        reverse=True,
    ):
        title = ""
        meta_path = thread_dir / "metainfo.json"
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                meta = {}
            raw = meta.get("title", "")
            title = raw if isinstance(raw, str) else ""
        entries.append({"id": thread_dir.name, "title": title})
    return entries


def emit_thread_list() -> None:
    """下发 ThreadList：home / threads_root 与 threads，供前端「恢复会话」。"""
    home = resolve_pagent_home()
    threads_root = default_threads_root()
    payload = {
        "jsonrpc": "2.0",
        "method": "ThreadList",
        "params": {
            "home": str(home),
            "threads_root": str(threads_root),
            "threads": list_thread_entries(),
        },
    }
    emit_line(json.dumps(payload, ensure_ascii=False) + "\n")


def make_title(text: str) -> str:
    """把首条用户消息压成一行标题：折叠空白、去首尾、超长截断加省略号。"""
    one_line = " ".join(text.split())
    if len(one_line) <= TITLE_MAX_CHARS:
        return one_line
    return one_line[:TITLE_MAX_CHARS] + "…"


def touch_thread_metainfo(runner, user_text: str) -> None:
    """更新 thread 的 metainfo.json：首条用户消息定标题，每轮刷新时间戳与消息数。

    title 是面向用户的会话名（取首条用户消息截断），一旦写入不再被后续消息覆盖；
    thread_id（thread-<时间戳>）是内部管理编号，不作展示。

    Args:
        runner: 当前会话 runner，用于取 thread 与消息数。
        user_text: 本轮用户输入，供首次生成 title。
    """
    thread = runner.thread
    metainfo = thread.load_metainfo()
    now = datetime.now().isoformat(timespec="seconds")
    metainfo.setdefault("created_at", now)
    metainfo.setdefault("title", make_title(user_text))
    metainfo["updated_at"] = now
    metainfo["message_count"] = len(runner.messages.data)
    thread.save_metainfo(metainfo)


# slash 命令清单：name 是不带 / 的命令名，summary 供前端菜单展示。
# 顺序即前端菜单展示顺序；实际执行分派见 run_slash_command。
SLASH_COMMANDS: list[dict[str, str]] = [
    {"name": "help", "summary": "列出所有可用的 slash 命令"},
    {"name": "skills", "summary": "已加载的技能及其描述"},
    {"name": "history", "summary": "当前会话的消息概览"},
    {"name": "pwd", "summary": "沙箱当前工作目录"},
    {"name": "ls", "summary": "列出沙箱主目录下的文件"},
]


def emit_slash_commands() -> None:
    """下发可用 slash 命令清单，供前端填充输入框旁的斜杠菜单。

    清单以本进程为准，前端只负责展示，避免前后端各维护一份导致漂移。
    """
    payload = {
        "jsonrpc": "2.0",
        "method": "SlashCommands",
        "params": {"commands": SLASH_COMMANDS},
    }
    emit_line(json.dumps(payload, ensure_ascii=False) + "\n")


def emit_slash_result(name: str, text: str, *, ok: bool = True) -> None:
    """把一次 slash 命令的执行结果回给前端，渲染成一张命令结果卡。

    Args:
        name: 命令名（不带 /），前端用作卡片标题。
        text: 结果正文（多行纯文本）。
        ok: 是否执行成功，前端据此配色（未知命令等走失败态）。
    """
    payload = {
        "jsonrpc": "2.0",
        "method": "SlashResult",
        "params": {"name": name, "text": text, "ok": ok},
    }
    emit_line(json.dumps(payload, ensure_ascii=False) + "\n")


def format_slash_help() -> str:
    """把 slash 命令清单排成对齐的帮助文本。"""
    width = max(len(item["name"]) for item in SLASH_COMMANDS)
    lines = [f"/{item['name']:<{width}}  {item['summary']}" for item in SLASH_COMMANDS]
    return "\n".join(lines)


async def run_slash_command(name: str, runner) -> None:
    """执行一条 slash 命令，结果通过 SlashResult 事件回前端；不跑 Agent。

    复用 REPL 的只读能力，但把输出收集成字符串而非直接打印，保持 stdout 是纯事件流。

    Args:
        name: 命令名（不带 /）。
        runner: 当前会话 runner，提供 sandbox / skills / messages 等只读视图。
    """
    if name in ("", "help"):
        emit_slash_result("help", format_slash_help())
        return

    if name == "skills":
        skills = runner.skills.list()
        if not skills:
            emit_slash_result("skills", "(未加载任何技能)")
            return
        text = "\n".join(f"{skill.name}: {skill.description}" for skill in skills)
        emit_slash_result("skills", text)
        return

    if name == "history":
        lines = []
        for message in runner.messages.data:
            preview = str(message.content)[:80].replace("\n", " ")
            lines.append(f"[{message.role}] {preview}")
        emit_slash_result("history", "\n".join(lines) or "(空会话)")
        return

    if name == "pwd":
        emit_slash_result("pwd", runner.sandbox.workdir)
        return

    if name == "ls":
        entries = await runner.sandbox.files.list(runner.sandbox.home)
        lines = [f"{'d' if entry.is_dir else 'f'} {entry.name}" for entry in entries]
        emit_slash_result("ls", "\n".join(lines) or "(空目录)")
        return

    emit_slash_result(name, f"未知命令：/{name}", ok=False)


def emit_error(message: str, *, where: str = "") -> None:
    """把错误回给前端：撤掉 loading，展示错误气泡。

    这是 wire 层控制事件（与 PermitRequest / HistoryReplay 同类），不是 core Event。
    """
    payload = {
        "jsonrpc": "2.0",
        "method": "Error",
        "params": {"message": message, "where": where},
    }
    emit_line(json.dumps(payload, ensure_ascii=False) + "\n")


def format_exc(exc: BaseException) -> str:
    """把异常收成一行可读信息；SystemExit 的 code 可能是字符串。"""
    if isinstance(exc, SystemExit):
        code = exc.code
        if isinstance(code, str) and code.strip():
            return code.strip()
        if code not in (None, 0):
            return f"进程退出 code={code}"
        return "进程退出"
    return str(exc) or exc.__class__.__name__


async def run_user_turn(runner, text: str, config: ReplConfig, state: dict) -> None:
    """跑一轮 Agent，事件逐行透传 stdout；需审批工具补发 PermitRequest。"""
    ask_permit = not config.permission_auto()
    try:
        async for event in runner.run(text, return_type="event"):
            emit_line(encode_event_line(event))
            if (
                ask_permit
                and isinstance(event, ToolCallBegin)
                and needs_tool_permit(event.name)
            ):
                emit_permit_request(event)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log(f"[wire] turn failed: {exc}")
        emit_error(format_exc(exc), where="turn")
    finally:
        state["turn"] = None


def turn_active(state: dict) -> bool:
    """当前是否有一轮 Agent 还在后台跑。"""
    task = state.get("turn")
    return task is not None and not task.done()


async def open_fresh_runner(config: ReplConfig):
    """开一个干净会话：thread_id 置空，让 open_runner 生成新的 thread-<时间戳>。"""
    return await open_runner(replace(config, thread_id=None))


async def open_thread_runner(config: ReplConfig, thread_id: str):
    """切到指定 thread：沿用其磁盘上的 spec 与历史消息（Runner.create 会载入）。"""
    return await open_runner(replace(config, thread_id=thread_id))


async def ensure_runner(runner, config: ReplConfig):
    """惰性打开 runner：进程先 ready 收命令，真正要用会话时再唤醒沙箱。"""
    if runner is not None:
        return runner
    return await open_fresh_runner(config)


def emit_empty_history_replay() -> None:
    """前端加载失败/无会话时用空 HistoryReplay 解除骨架屏。"""
    payload = {
        "jsonrpc": "2.0",
        "method": "HistoryReplay",
        "params": {"thread_id": "", "title": "", "messages": []},
    }
    emit_line(json.dumps(payload, ensure_ascii=False) + "\n")


async def handle_command(command: dict, runner, config: ReplConfig, state: dict):
    """按命令类型分派；返回当前 runner（reset/resume 时可能换成新 runner）。

    ``runner`` 可为 None：进程启动时尚未 open，避免切换 backend 后先卡在空会话的
    沙箱唤醒上，导致 stdin 里的 resume 迟迟得不到处理。
    """
    cmd = command.get("cmd")

    if cmd == "commands":
        emit_slash_commands()
        return runner

    if cmd == "list_threads":
        emit_thread_list()
        return runner

    if cmd == "resume":
        thread_id = command.get("thread_id")
        if not (isinstance(thread_id, str) and thread_id):
            log("[wire] resume missing thread_id")
            return runner
        if turn_active(state):
            log("[wire] 运行中，暂不能切换会话（取消见后续课程）")
            return runner
        old = runner
        try:
            runner = await open_thread_runner(config, thread_id)
        except (Exception, SystemExit) as exc:
            log(f"[wire] resume failed: {exc}")
            if old is None:
                emit_empty_history_replay()
            else:
                emit_history_replay(old)
            emit_error(format_exc(exc), where="resume")
            return old
        if old is not None:
            await old.close()
        emit_history_replay(runner)
        log(f"[wire] resume：已切到 thread {thread_id!r}")
        return runner

    if cmd == "reset":
        if turn_active(state):
            log("[wire] 运行中，暂不能新建会话（取消见后续课程）")
            return runner
        if runner is not None:
            await runner.close()
        runner = await open_fresh_runner(config)
        emit_history_replay(runner)
        log("[wire] reset：已开新会话")
        return runner

    if cmd == "cancel":
        log("[wire] cancel received (并发取消见后续课程)")
        return runner

    # 以下命令需要已打开的 runner。
    try:
        runner = await ensure_runner(runner, config)
    except (Exception, SystemExit) as exc:
        log(f"[wire] open runner failed: {exc}")
        emit_error(format_exc(exc), where="open")
        return runner

    if cmd == "user":
        text = command.get("text", "")
        if not isinstance(text, str) or not text.strip():
            log("[wire] user command missing text")
            return runner
        # 以 / 开头的走 slash 命令：本地只读能力，不跑 Agent、不进对话历史。
        if text.lstrip().startswith("/"):
            try:
                await run_slash_command(text.strip().lstrip("/").split()[0], runner)
            except Exception as exc:
                log(f"[wire] slash failed: {exc}")
                emit_error(format_exc(exc), where="slash")
            return runner
        if turn_active(state):
            log("[wire] 上一轮还在跑，忽略新 user（一次一轮）")
            return runner
        # 落一次 metainfo：首条用户消息定标题，供前端会话列表展示面向用户的名字。
        touch_thread_metainfo(runner, text)
        state["turn"] = asyncio.create_task(run_user_turn(runner, text, config, state))
        return runner

    if cmd == "permit":
        tool_call_id = command.get("tool_call_id")
        if isinstance(tool_call_id, str) and tool_call_id:
            runner.inbound.permit(tool_call_id)
        else:
            log("[wire] permit missing tool_call_id")
        return runner

    if cmd == "deny":
        tool_call_id = command.get("tool_call_id")
        if not (isinstance(tool_call_id, str) and tool_call_id):
            log("[wire] deny missing tool_call_id")
            return runner
        reason = command.get("reason", "")
        runner.inbound.deny(
            tool_call_id, reason=reason if isinstance(reason, str) else ""
        )
        return runner

    log(f"[wire] unknown command: {cmd!r}")
    return runner


async def run_wire(config: ReplConfig) -> int:
    """进入 stdin 命令循环。

    默认惰性打开 runner：先 ``ready`` 再收命令。若 CLI 带了 ``--thread-id``，
    启动时直接打开该 thread 并回放历史（给非插件调用方用）。
    """
    runner = None
    state: dict = {"turn": None}
    had_user_turn = False
    # 启动即下发 slash 命令清单，前端无需显式请求就能填充斜杠菜单。
    emit_slash_commands()
    if config.thread_id:
        runner = await open_thread_runner(config, config.thread_id)
        emit_history_replay(runner)
    log("[wire] ready")
    try:
        while True:
            # 用线程读阻塞的 stdin，避免占死事件循环；后台 turn task 得以并发推进。
            line = await asyncio.to_thread(sys.stdin.readline)
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            command = parse_command(line)
            if command is None:
                continue
            prev_count = len(runner.messages.data) if runner is not None else 0
            runner = await handle_command(command, runner, config, state)
            if runner is not None and len(runner.messages.data) > prev_count:
                had_user_turn = True
    finally:
        task = state.get("turn")
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if runner is not None:
            thread_id = runner.thread.id
            await runner.close()
            keep = {thread_id} if had_user_turn else set()
            report = clean_pagent(keep_thread_ids=keep)
            clean_message = format_clean_report(report)
            if clean_message:
                log(f"[wire] {clean_message}")
    return 0

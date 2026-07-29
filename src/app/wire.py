"""electromind --wire —— stdio NDJSON 后端，供外部前端（如 VS Code 插件）驱动 Agent。

三条流各司其职：

- **stdout**：每行一个事件（Wire 协议）。透传 ``runner.run(return_type="event")``
  产出的事件，用 ``electromind/adapters/acp.py`` 的 ``encode_event_line`` 序列化；
  需审批的工具再补一条 ``PermitRequest`` 控制事件；失败时发 ``Error`` 控制事件
  （前端撤 loading 并展示错误气泡）。
- **stdin**：每行一个 JSON 命令，驱动 Agent。
- **stderr**：诊断日志，与事件流分开，前端可单独展示。

入站命令（前端 → 本进程）::

    {"cmd": "user", "text": "..."}                跑一轮 Agent，事件流式写到 stdout
    {"cmd": "user", "text": "/skills"}            以 / 开头的走 slash 命令，不跑 Agent
    {"cmd": "commands"}                           请求可用 slash 命令清单（供前端菜单）
    {"cmd": "history"}                            回放当前 thread 的历史，供 Webview 重建
    {"cmd": "permit", "tool_call_id": "..."}      批准某次工具调用
    {"cmd": "deny", "tool_call_id": "...", "reason": "..."}  拒绝某次工具调用
    {"cmd": "reset", ...}                         结束当前会话、开一个干净 thread
                                                  可选字段：project_path / backend /
                                                  image / ssh_host / ssh_config / ssh_workdir
    {"cmd": "resume", "thread_id": "..."}         切到已有 thread，回放其历史
    {"cmd": "list_threads"}                       列出当前 electromind home 下可恢复会话
    {"cmd": "delete_thread", "thread_id": "..."}  软删除：metainfo 打 deleted_at，列表隐藏
    {"cmd": "cancel"}                             取消当前运行中的 Agent 任务

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
import posixpath
import sys
import tomllib
from dataclasses import fields, replace
from datetime import datetime

from electromind import ToolCallBegin
from electromind.adapters.acp import encode_event_line, json_value
from electromind.core.context_limit import DEFAULT_CONTEXT_LIMIT, resolve_context_limit
from electromind.core.message import TextChunk, ThinkingChunk, ToolCall, ToolResult
from electromind.core.turn_result import TurnResult
from electromind.ithread import SPEC_FILENAME, ThreadSpec
from electromind.paths import resolve_electromind_home
from electromind.runtime.thread import Thread, default_threads_root

from .clean import clean_electromind, format_clean_report, iter_thread_dirs
from .config import ReplConfig, load_config, refresh_provider_from_disk
from .config_view import config_to_public_dict
from .environment import environment_check
from .repl import format_fatal_error, open_runner
from .setup import ProviderSetup, write_user_provider
from .tool_permit import needs_tool_permit, summarize_tool_args
from .transport import active_sink

# metainfo.json 里 title 的最大字符数：超出截断加省略号，供前端会话列表展示。
TITLE_MAX_CHARS = 40


def thread_context_limit(thread) -> int:
    """从 thread spec 的 model 名推断上下文窗口上限。"""
    spec = getattr(thread, "spec", None)
    model = getattr(spec, "model", None) if spec is not None else None
    if isinstance(model, str) and model.strip():
        return resolve_context_limit(model)
    return DEFAULT_CONTEXT_LIMIT


def log(text: str) -> None:
    """诊断日志写 stderr，避免污染 stdout 的事件流。"""
    print(text, file=sys.stderr, flush=True)


def emit_line(line: str) -> None:
    """把一行事件投递到当前活跃出口。line 已自带换行（encode_event_line 的约定）。

    wire 模式下出口是 stdout；http 模式下是广播给各 SSE 连接的 FanoutSink。
    命令处理核只调 emit_line，不关心传输。
    """
    active_sink().emit(line)


def runner_project_path(runner) -> str:
    """当前 thread 绑定的用户 project（host_root），不是沙箱 workspace。"""
    path = getattr(runner.thread, "project_path", None)
    if path is not None:
        return str(path)
    raw = getattr(runner.thread.spec, "project_path", None)
    return str(raw) if isinstance(raw, str) and raw else ""


def command_project_path(command: dict) -> str | None:
    """读取宿主传来的 project 目录；空值视为未指定。"""
    value = command.get("project_path")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


# reset 可携带的 ThreadSpec / ReplConfig 覆盖字段（字符串，空值忽略）。
_RESET_OVERRIDE_KEYS = (
    "backend",
    "image",
    "ssh_host",
    "ssh_config",
    "ssh_workdir",
    "project_path",
)


def apply_command_overrides(config: ReplConfig, command: dict) -> ReplConfig:
    """把 wire 命令里的可选字段叠到 ReplConfig，供 reset 按会话选 sandbox。"""
    updates: dict[str, str] = {}
    for key in _RESET_OVERRIDE_KEYS:
        value = command.get(key)
        if isinstance(value, str) and value.strip():
            updates[key] = value.strip()
    return replace(config, **updates) if updates else config


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


def history_message_items(messages) -> list[dict]:
    """把 Messages 规整成前端易渲染的简单数组，供 HistoryReplay 回放。

    每个 Message 存一个 content chunk（流式 text/thinking 已在存储层合并成一行），
    这里按 chunk 类型摊平成扁平记录，字段与前端渲染一一对应：

    - text/thinking：``{"kind": ..., "role": ..., "text": ...}``
    - 工具调用：``{"kind": "tool_call", "tool_call_id", "name", "arguments"}``
    - 工具结果：``{"kind": "tool_result", "tool_call_id", "content"}``

    system 消息不回放（前端不展示系统提示）。
    """
    out: list[dict] = []
    for message in messages.data:
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


def history_messages(runner) -> list[dict]:
    """把 runner.messages 规整成前端易渲染的简单数组。"""
    return history_message_items(runner.messages)


def emit_history_replay_payload(
    *,
    thread_id: str,
    title: str,
    project_path: str,
    messages: list[dict],
    usage: dict | None = None,
    context_limit: int | None = None,
) -> None:
    params: dict = {
        "thread_id": thread_id,
        "title": title,
        "project_path": project_path,
        "messages": messages,
    }
    if context_limit is not None and context_limit > 0:
        params["context_limit"] = context_limit
    if usage:
        params["usage"] = usage
    payload = {
        "jsonrpc": "2.0",
        "method": "HistoryReplay",
        "params": params,
    }
    emit_line(json.dumps(payload, ensure_ascii=False) + "\n")


def emit_history_replay(runner) -> None:
    """补发一条 HistoryReplay 控制事件，让前端重建会话视图。

    空数组表示新会话（前端清屏）；非空则前端逐条回放成气泡/思考/工具卡。
    与 PermitRequest 一样是 wire 层控制事件，套 JSON-RPC notification 形状。
    metainfo 里的 title 一并带上，前端据此在标题栏/列表展示面向用户的名字。
    持久化的 usage 快照（若有）随 params.usage 下发，供上下文 ring 恢复。
    """
    metainfo = runner.thread.load_metainfo()
    usage = metainfo.get("usage")
    limit = thread_context_limit(runner.thread)
    emit_history_replay_payload(
        thread_id=runner.thread.id,
        title=metainfo.get("title", ""),
        project_path=runner_project_path(runner),
        messages=history_messages(runner),
        usage=usage if isinstance(usage, dict) else None,
        context_limit=limit,
    )


def emit_thread_history_replay(thread, project_path: str | None = None) -> None:
    """只读取 thread 配置与消息，不打开 sandbox，用于轻量切换会话。"""
    bound = getattr(thread, "project_path", None)
    resolved = project_path or (str(bound) if bound is not None else "")
    messages = thread.load_messages()
    if messages.complete_orphan_tool_results():
        store = thread.open_store()
        store.save(thread.messages_conversation_id, messages)
        close = getattr(store, "close", None)
        if callable(close):
            close()
    metainfo = thread.load_metainfo()
    usage = metainfo.get("usage")
    limit = thread_context_limit(thread)
    emit_history_replay_payload(
        thread_id=thread.id,
        title=metainfo.get("title", ""),
        project_path=resolved,
        messages=history_message_items(messages),
        usage=usage if isinstance(usage, dict) else None,
        context_limit=limit,
    )


def emit_current_thread(runner) -> None:
    """告诉宿主当前 thread id，供 Webview 被销毁后自动恢复。"""
    payload = {
        "jsonrpc": "2.0",
        "method": "CurrentThread",
        "params": {
            "thread_id": runner.thread.id,
            "title": runner.thread.load_metainfo().get("title", ""),
            "project_path": runner_project_path(runner),
        },
    }
    emit_line(json.dumps(payload, ensure_ascii=False) + "\n")


def thread_spec(thread_dir) -> ThreadSpec | None:
    """读取 thread.toml；配置损坏时忽略该配置。"""
    spec_path = thread_dir / SPEC_FILENAME
    if not spec_path.is_file():
        return None
    try:
        return ThreadSpec.from_dict(load_toml_file(spec_path))
    except (OSError, ValueError):
        return None


def load_toml_file(path) -> dict:
    with path.open("rb") as fp:
        return tomllib.load(fp)


def thread_is_soft_deleted(meta: dict) -> bool:
    """metainfo 里有非空 deleted_at 即视为软删除，列表扫描时隐藏。"""
    value = meta.get("deleted_at")
    return isinstance(value, str) and bool(value.strip())


def soft_delete_thread(thread_id: str) -> None:
    """给 thread 的 metainfo 打上 deleted_at，不删磁盘目录。"""
    thread = Thread.open(thread_id)
    metainfo = thread.load_metainfo()
    if thread_is_soft_deleted(metainfo):
        return
    metainfo["deleted_at"] = datetime.now().isoformat(timespec="seconds")
    thread.save_metainfo(metainfo)


def list_thread_entries(project_path: str | None = None) -> list[dict[str, str]]:
    """按当前 cwd 解析的 electromind home 列出可恢复 thread（与落盘同一判定）。

    委托给 ``app.sessions.list_sessions``，再把 SessionInfo 转成前端 wire 协议需要的 dict。
    """
    from app.sessions import list_sessions

    sessions = list_sessions()
    entries: list[dict[str, str]] = []
    for s in sessions:
        entries.append(
            {
                "id": s.id,
                "title": s.title,
                "project_path": s.project_path or project_path or "",
                "backend": s.backend,
            }
        )
    return entries


def emit_thread_list(project_path: str | None = None) -> None:
    """下发 ThreadList：home / threads_root 与 threads，供前端「恢复会话」。"""
    home = resolve_electromind_home()
    threads_root = default_threads_root()
    payload = {
        "jsonrpc": "2.0",
        "method": "ThreadList",
        "params": {
            "home": str(home),
            "threads_root": str(threads_root),
            "threads": list_thread_entries(project_path),
        },
    }
    emit_line(json.dumps(payload, ensure_ascii=False) + "\n")


def resolved_backend_name(runner) -> str:
    """返回当前运行 sandbox 的真实 backend 名称。"""
    backend = runner.sandbox.backend
    inner = getattr(backend, "inner", backend)
    class_name = inner.__class__.__name__
    if class_name == "LocalBackend":
        return "local"
    if class_name == "DockerBackend":
        return "docker"
    if class_name == "PodmanBackend":
        return "podman"
    if class_name == "SshBackend":
        return "ssh"
    return runner.thread.spec.backend


def emit_sandbox_status_payload(
    *,
    thread_id: str,
    backend: str,
    alive: bool,
    workdir: str,
) -> None:
    """下发一条 SandboxStatus 事件。"""
    payload = {
        "jsonrpc": "2.0",
        "method": "SandboxStatus",
        "params": {
            "thread_id": thread_id,
            "backend": backend,
            "alive": alive,
            "workdir": workdir,
        },
    }
    emit_line(json.dumps(payload, ensure_ascii=False) + "\n")


def emit_skills(runner) -> None:
    """下发当前会话已加载的 skills 列表，供前端渲染技能面板。"""
    skills = runner.skills.list() if runner else []
    payload = {
        "jsonrpc": "2.0",
        "method": "Skills",
        "params": {
            "skills": [
                {
                    "name": skill.name,
                    "description": skill.description,
                    "path": str(skill.root),
                }
                for skill in skills
            ],
        },
    }
    emit_line(json.dumps(payload, ensure_ascii=False) + "\n")


async def emit_sandbox_status(runner) -> None:
    """下发当前 sandbox 的类型与存活状态，供宿主顶部状态栏展示。"""
    if runner is None:
        emit_sandbox_status_payload(
            thread_id="",
            backend="",
            alive=False,
            workdir="",
        )
        return

    backend = resolved_backend_name(runner)
    alive = False
    try:
        alive = await asyncio.wait_for(runner.sandbox.backend.alive(), timeout=3)
    except Exception as exc:
        log(f"[wire] sandbox_status probe failed: {exc}")

    emit_sandbox_status_payload(
        thread_id=runner.thread.id,
        backend=backend,
        alive=alive,
        workdir=runner.sandbox.workdir,
    )


async def build_sandbox_tree(runner, virtual_path: str, prefix: str = "") -> list[dict]:
    """递归列出当前 sandbox workdir 的目录树。

    统一走运行中的 sandbox 接口，而不是猜本地磁盘路径，这样 local/container/ssh
    都能返回同一语义的树。
    """
    try:
        entries = await runner.sandbox.files.list(virtual_path)
    except Exception as exc:
        log(f"[wire] sandbox_tree skip {virtual_path!r}: {exc}")
        return []
    nodes: list[dict] = []
    for entry in entries:
        node_id = f"{prefix}/{entry.name}" if prefix else entry.name
        if entry.is_dir:
            child_path = posixpath.join(virtual_path, entry.name)
            children = await build_sandbox_tree(runner, child_path, node_id)
            nodes.append(
                {
                    "id": node_id,
                    "label": entry.name,
                    "kind": "dir",
                    "count": len(children),
                    "children": children,
                }
            )
            continue
        nodes.append(
            {
                "id": node_id,
                "label": entry.name,
                "kind": "file",
            }
        )
    return nodes


async def emit_sandbox_tree(runner) -> None:
    """下发当前 sandbox workdir 的目录树，供宿主渲染右侧文件树。"""
    if runner is None:
        payload = {
            "jsonrpc": "2.0",
            "method": "SandboxTree",
            "params": {
                "thread_id": "",
                "workdir": "",
                "nodes": [],
            },
        }
        emit_line(json.dumps(payload, ensure_ascii=False) + "\n")
        return

    payload = {
        "jsonrpc": "2.0",
        "method": "SandboxTree",
        "params": {
            "thread_id": runner.thread.id,
            "workdir": runner.sandbox.workdir,
            "nodes": await build_sandbox_tree(runner, runner.sandbox.home),
        },
    }
    emit_line(json.dumps(payload, ensure_ascii=False) + "\n")


def make_title(text: str) -> str:
    """把首条用户消息压成一行标题：折叠空白、去首尾、超长截断加省略号。"""
    one_line = " ".join(text.split())
    if len(one_line) <= TITLE_MAX_CHARS:
        return one_line
    return one_line[:TITLE_MAX_CHARS] + "…"


def build_usage_snapshot(
    usage: dict | None,
    *,
    context_limit: int = DEFAULT_CONTEXT_LIMIT,
) -> dict | None:
    """把 TurnResult.usage 规整成可写入 metainfo.json 的扁平快照。"""
    if not isinstance(usage, dict):
        return None
    prompt = usage.get("prompt_tokens")
    if not isinstance(prompt, int) or prompt <= 0:
        return None

    prompt_details = usage.get("prompt_tokens_details")
    completion_details = usage.get("completion_tokens_details")
    cached = 0
    cache_write = 0
    if isinstance(prompt_details, dict):
        cached = prompt_details.get("cached_tokens") or 0
        cache_write = prompt_details.get("cache_write_tokens") or 0
    reasoning = 0
    if isinstance(completion_details, dict):
        reasoning = completion_details.get("reasoning_tokens") or 0
    completion = usage.get("completion_tokens") or 0

    return {
        "context_limit": context_limit,
        "prompt_tokens": prompt,
        "cached_tokens": min(int(cached), prompt),
        "cache_write_tokens": int(cache_write) if cache_write else 0,
        "completion_tokens": int(completion) if completion else 0,
        "reasoning_tokens": int(reasoning) if reasoning else 0,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def touch_thread_usage(
    thread,
    usage: dict | None,
    *,
    context_limit: int = DEFAULT_CONTEXT_LIMIT,
) -> None:
    """把最近一次 LLM 调用的 usage 快照写入 metainfo.json。"""
    snapshot = build_usage_snapshot(usage, context_limit=context_limit)
    if snapshot is None:
        return
    metainfo = thread.load_metainfo()
    metainfo["usage"] = snapshot
    thread.save_metainfo(metainfo)


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
    {"name": "sessions", "summary": "列出所有历史会话"},
    {"name": "resume", "summary": "切换会话（无参数列出，指定 ID 直接切换）"},
    {"name": "pwd", "summary": "沙箱当前工作目录"},
    {"name": "ls", "summary": "列出沙箱主目录下的文件"},
]


def slash_commands_line() -> str:
    """构造 SlashCommands 事件行（不写出口）。供 wire 启动推送与 http 新连接回放复用。"""
    payload = {
        "jsonrpc": "2.0",
        "method": "SlashCommands",
        "params": {"commands": SLASH_COMMANDS},
    }
    return json.dumps(payload, ensure_ascii=False) + "\n"


def emit_slash_commands() -> None:
    """下发可用 slash 命令清单，供前端填充输入框旁的斜杠菜单。

    清单以本进程为准，前端只负责展示，避免前后端各维护一份导致漂移。
    """
    emit_line(slash_commands_line())


def emit_config_snapshot(config: ReplConfig) -> None:
    """下发脱敏后的配置快照，供前端渲染设置面板。api_key 从不原样下发。"""
    payload = {
        "jsonrpc": "2.0",
        "method": "ConfigSnapshot",
        "params": config_to_public_dict(config),
    }
    emit_line(json.dumps(payload, ensure_ascii=False) + "\n")


def emit_thread_meta(thread_id: str, meta: dict) -> None:
    """下发单个 thread 的 metainfo，供前端在不 resume 的情况下取标题/用量等。"""
    payload = {
        "jsonrpc": "2.0",
        "method": "ThreadMeta",
        "params": {"thread_id": thread_id, "meta": meta},
    }
    emit_line(json.dumps(payload, ensure_ascii=False) + "\n")


def emit_environment_check(check: dict) -> None:
    """下发 server 机器环境自检结果，供前端渲染环境/诊断面板。"""
    payload = {
        "jsonrpc": "2.0",
        "method": "EnvironmentCheck",
        "params": check,
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

    if name in ("sessions", "resume"):
        emit_thread_list()
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


def client_feature_enabled(state: dict, name: str) -> bool:
    """当前连接是否显式打开了某个前端实验能力。"""
    features = state.get("client_features")
    if not isinstance(features, dict):
        return False
    return bool(features.get(name))


def emit_subagent_event(name: str, conversation_id: str, event) -> None:
    """把子 agent 内部事件包成 wire 控制事件，供 desktop 实验消费。"""
    payload = {
        "jsonrpc": "2.0",
        "method": "SubagentEvent",
        "params": {
            "name": name,
            "conversation_id": conversation_id,
            "event": {
                "method": type(event).__name__,
                "params": {
                    field.name: json_value(getattr(event, field.name))
                    for field in fields(event)
                },
            },
        },
    }
    emit_line(json.dumps(payload, ensure_ascii=False) + "\n")


def install_subagent_observer(runner, state: dict):
    """按客户端能力开关给 runner 临时装上子 agent 事件旁路。"""
    if not client_feature_enabled(state, "subagent_events"):
        return lambda: None

    previous = getattr(runner, "observe_subagent_event", None)

    def observer(*, name: str, conversation_id: str, event) -> None:
        emit_subagent_event(name, conversation_id, event)

    runner.observe_subagent_event = observer

    def restore() -> None:
        if previous is None:
            try:
                delattr(runner, "observe_subagent_event")
            except AttributeError:
                pass
            return
        runner.observe_subagent_event = previous

    return restore


def format_exc(exc: BaseException, *, phase: str = "start") -> str:
    """把异常收成可读信息；沙箱启动失败走 format_fatal_error（含 SSH 提示）。"""
    if isinstance(exc, SystemExit):
        code = exc.code
        if isinstance(code, str) and code.strip():
            return code.strip()
        if code not in (None, 0):
            return f"进程退出 code={code}"
        return "进程退出"
    return format_fatal_error(exc, phase=phase)


async def run_user_turn(runner, text: str, config: ReplConfig, state: dict) -> None:
    """跑一轮 Agent，事件逐行透传 stdout；需审批工具补发 PermitRequest。"""
    ask_permit = not config.permission_auto()
    last_usage: dict | None = None
    restore_subagent_observer = install_subagent_observer(runner, state)
    try:
        async for event in runner.run(text, return_type="event"):
            emit_line(encode_event_line(event))
            if isinstance(event, TurnResult) and event.usage:
                last_usage = event.usage
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
        restore_subagent_observer()
        if last_usage is not None:
            touch_thread_usage(
                runner.thread,
                last_usage,
                context_limit=thread_context_limit(runner.thread),
            )
        state["turn"] = None


def turn_active(state: dict) -> bool:
    """当前是否有一轮 Agent 还在后台跑。"""
    task = state.get("turn")
    return task is not None and not task.done()


async def open_fresh_runner(config: ReplConfig, project_path: str | None = None):
    """开一个干净会话：thread_id 置空，让 open_runner 生成新的 thread-<时间戳>。"""
    if project_path is not None:
        config = replace(config, project_path=project_path)
    return await open_runner(replace(config, thread_id=None))


def clean_empty_threads(*, keep_thread_ids: set[str] | frozenset[str] = frozenset()):
    """清理没有用户消息的空会话，供 reset/退出路径复用。"""
    report = clean_electromind(keep_thread_ids=keep_thread_ids)
    clean_message = format_clean_report(report)
    if clean_message:
        log(f"[wire] {clean_message}")
    return report


async def open_thread_runner(
    config: ReplConfig, thread_id: str, project_path: str | None = None
):
    """切到指定 thread：沿用其磁盘上的 spec 与历史消息（Runner.create 会载入）。"""
    if project_path is not None:
        config = replace(config, project_path=project_path)
    return await open_runner(replace(config, thread_id=thread_id))


def open_thread_history(thread_id: str, project_path: str | None = None):
    """轻量打开 thread：只读 thread.toml/metainfo/messages，不启动 sandbox。"""
    overrides = {"project_path": project_path} if project_path else None
    return Thread.open(thread_id, overrides=overrides)


async def ensure_runner(runner, config: ReplConfig, state: dict):
    """惰性打开 runner：进程先 ready 收命令，真正要用会话时再唤醒沙箱。"""
    if runner is not None:
        return runner
    thread_id = state.get("thread_id")
    if isinstance(thread_id, str) and thread_id:
        project_path = state.get("project_path")
        return await open_thread_runner(
            config,
            thread_id,
            project_path if isinstance(project_path, str) else None,
        )
    return await open_fresh_runner(config)


def emit_empty_history_replay() -> None:
    """前端加载失败/无会话时用空 HistoryReplay 解除骨架屏。"""
    payload = {
        "jsonrpc": "2.0",
        "method": "HistoryReplay",
        "params": {"thread_id": "", "title": "", "project_path": "", "messages": []},
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

    if cmd == "client_features":
        features = command.get("features")
        state["client_features"] = {
            "subagent_events": bool(
                features.get("subagent_events", False)
                if isinstance(features, dict)
                else False
            )
        }
        return runner

    if cmd == "get_config":
        emit_config_snapshot(load_config())
        return runner

    if cmd == "set_provider":
        api_key = command.get("api_key")
        if not (isinstance(api_key, str) and api_key.strip()):
            log("[wire] set_provider missing api_key")
            emit_error("api_key 不能为空", where="set_provider")
            return runner
        model = command.get("model")
        base_url = command.get("base_url")
        setup = ProviderSetup(api_key=api_key.strip())
        if isinstance(model, str) and model.strip():
            setup.model = model.strip()
        if isinstance(base_url, str) and base_url.strip():
            setup.base_url = base_url.strip()
        try:
            write_user_provider(setup)
        except (Exception, SystemExit) as exc:
            log(f"[wire] set_provider failed: {exc}")
            emit_error(format_exc(exc, phase="start"), where="set_provider")
            return runner
        # 写盘后回读一份脱敏快照，让前端确认生效；已开的 runner 由下次 open 时热刷新。
        emit_config_snapshot(refresh_provider_from_disk(load_config()))
        return runner

    if cmd == "thread_meta":
        thread_id = command.get("thread_id")
        if not (isinstance(thread_id, str) and thread_id.strip()):
            log("[wire] thread_meta missing thread_id")
            emit_error("缺少 thread_id", where="thread_meta")
            return runner
        thread_id = thread_id.strip()
        try:
            meta = Thread.open(thread_id).load_metainfo()
        except (Exception, SystemExit) as exc:
            log(f"[wire] thread_meta failed: {exc}")
            emit_error(format_exc(exc, phase="start"), where="thread_meta")
            return runner
        emit_thread_meta(thread_id, meta)
        return runner

    if cmd == "environment_check":
        include_disk = bool(command.get("include_disk", False))
        emit_environment_check(environment_check(include_disk=include_disk))
        return runner

    if cmd == "history":
        if runner is not None:
            emit_history_replay(runner)
            return runner
        thread_id = state.get("thread_id")
        if isinstance(thread_id, str) and thread_id:
            project_path = command_project_path(command)
            emit_thread_history_replay(
                open_thread_history(thread_id, project_path),
                project_path,
            )
        return runner

    if cmd == "list_threads":
        emit_thread_list(command_project_path(command))
        return runner

    if cmd == "delete_thread":
        thread_id = command.get("thread_id")
        if not (isinstance(thread_id, str) and thread_id.strip()):
            log("[wire] delete_thread missing thread_id")
            return runner
        thread_id = thread_id.strip()
        try:
            soft_delete_thread(thread_id)
        except (Exception, SystemExit) as exc:
            log(f"[wire] delete_thread failed: {exc}")
            emit_error(format_exc(exc, phase="start"), where="delete_thread")
            return runner
        # 删的是当前会话：关掉 runner 并空回放，前端清屏；不自动开新会话。
        deleted_current = False
        if runner is not None and runner.thread.id == thread_id:
            await runner.close()
            runner = None
            deleted_current = True
        if state.get("thread_id") == thread_id:
            state["thread_id"] = None
            deleted_current = True
        if deleted_current:
            emit_empty_history_replay()
        emit_thread_list(command_project_path(command))
        log(f"[wire] delete_thread：已软删除 {thread_id}")
        return runner

    if cmd == "sandbox_tree":
        # 状态/树查询不唤醒沙箱：SSH 连不上时 ensure_runner 会堵死 stdin 命令循环，
        # 连 cancel 都进不来。沙箱只在 user/reset 等显式路径打开。
        await emit_sandbox_tree(runner)
        return runner

    if cmd == "sandbox_status":
        if runner is None:
            thread_id = (
                state["thread_id"] if isinstance(state.get("thread_id"), str) else ""
            )
            backend = ""
            if thread_id:
                try:
                    project_path = state.get("project_path")
                    thread = open_thread_history(
                        thread_id,
                        project_path if isinstance(project_path, str) else None,
                    )
                    backend = thread.spec.backend or ""
                except Exception as exc:
                    log(f"[wire] sandbox_status meta failed: {exc}")
            emit_sandbox_status_payload(
                thread_id=thread_id,
                backend=backend,
                alive=False,
                workdir="",
            )
            return runner
        await emit_sandbox_status(runner)
        return runner

    if cmd == "skills":
        emit_skills(runner)
        return runner

    if cmd == "resume":
        thread_id = command.get("thread_id")
        if not (isinstance(thread_id, str) and thread_id):
            log("[wire] resume missing thread_id")
            return runner
        if turn_active(state):
            log("[wire] resume rejected: turn active")
            emit_error(
                "助手正在运行，无法切换会话。请等待完成或先停止当前任务。",
                where="resume",
            )
            return runner
        project_path = command_project_path(command)
        try:
            thread = open_thread_history(thread_id, project_path)
            if thread_is_soft_deleted(thread.load_metainfo()):
                raise ValueError(f"会话已删除：{thread_id}")
        except (Exception, SystemExit) as exc:
            log(f"[wire] resume failed: {exc}")
            if runner is None:
                emit_empty_history_replay()
            else:
                emit_history_replay(runner)
            emit_error(format_exc(exc, phase="start"), where="resume")
            return runner
        if runner is not None:
            await runner.close()
            runner = None
        state["thread_id"] = thread.id
        state["project_path"] = project_path
        emit_thread_history_replay(thread)
        return None

    if cmd == "reset":
        if turn_active(state):
            log("[wire] reset rejected: turn active")
            emit_error(
                "助手正在运行，无法新建会话。请等待完成或先停止当前任务。",
                where="reset",
            )
            return runner
        previous_thread_id = (
            runner.thread.id if runner is not None else state.get("thread_id")
        )
        if runner is not None:
            await runner.close()
            runner = None
        if isinstance(previous_thread_id, str):
            clean_empty_threads()
        reset_config = apply_command_overrides(config, command)
        project_path = reset_config.project_path
        try:
            runner = await open_fresh_runner(reset_config, project_path)
        except (Exception, SystemExit) as exc:
            log(f"[wire] reset failed: {exc}")
            state["thread_id"] = None
            state["project_path"] = project_path
            # Thread.open 已落盘，沙箱启动失败时清掉这个空会话，避免列表里留僵尸 thread。
            clean_empty_threads()
            emit_empty_history_replay()
            emit_error(format_exc(exc, phase="start"), where="reset")
            return None
        state["thread_id"] = runner.thread.id
        state["project_path"] = project_path
        emit_history_replay(runner)
        log(
            "[wire] reset：已开新会话"
            + (f" backend={reset_config.backend}" if reset_config.backend else "")
        )
        return runner

    if cmd == "cancel":
        if runner is not None and turn_active(state):
            runner.cancel_run()
            log("[wire] cancel：已请求停止当前任务")
        else:
            log("[wire] cancel：当前没有运行中的任务")
        return runner

    # 以下命令需要已打开的 runner。
    opened_runner = runner is None
    try:
        project_path = command_project_path(command) if runner is None else None
        runner = await ensure_runner(
            runner,
            replace(config, project_path=project_path) if project_path else config,
            state,
        )
    except (Exception, SystemExit) as exc:
        log(f"[wire] open runner failed: {exc}")
        emit_error(format_exc(exc), where="open")
        return runner
    if opened_runner:
        state["thread_id"] = runner.thread.id
        emit_current_thread(runner)

    if cmd == "user":
        text = command.get("text", "")
        if not isinstance(text, str) or not text.strip():
            log("[wire] user command missing text")
            return runner
        # 以 / 开头的走 slash 命令：本地只读能力，不跑 Agent、不进对话历史。
        # 只有已知命令才拦截；未知的 /xxx（含绝对路径）按普通文本交给 Agent。
        if text.lstrip().startswith("/"):
            cmd_name = text.strip().lstrip("/").split()[0]
            known_commands = {item["name"] for item in SLASH_COMMANDS}
            if cmd_name in known_commands:
                try:
                    await run_slash_command(cmd_name, runner)
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
    state: dict = {"turn": None, "client_features": {}}
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
            clean_empty_threads(keep_thread_ids={thread_id} if had_user_turn else set())
    return 0

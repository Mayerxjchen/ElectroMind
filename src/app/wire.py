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
from electromind.harness import (
    InputDelivery,  # used in handle_command input/send handler
    InputMessage,  # used in handle_command input/send handler
    ThreadSessionManager,
)
from electromind.ithread import SPEC_FILENAME, ThreadSpec
from electromind.paths import resolve_electromind_home
from electromind.runtime.thread import Thread, default_threads_root

from .clean import clean_electromind, format_clean_report
from .config import ReplConfig, load_config, refresh_provider_from_disk
from .config_view import config_to_public_dict
from .environment import environment_check
from .repl import format_fatal_error, open_runner
from .setup import ProviderSetup, write_user_provider
from .tool_permit import needs_tool_permit, summarize_tool_args
from .transport import active_sink

# Per-process harness session manager (shared across wire/HTTP transports)
_harness_manager: ThreadSessionManager = ThreadSessionManager()
_harness_broker = None  # Lazy-init: protocol_v2.EventBroker()
_harness_idempotency = None  # Lazy-init: protocol_v2.IdempotencyStore()
# M1: 唯一 RunEngine —— wire/http 共用同一实例（与 _harness_manager 同源）
_wire_engine = None  # Lazy-init: engine.RunEngine(manager=_harness_manager)


def _get_engine():
    """返回共享 RunEngine（M1：唯一 Run 生命周期实现）。

    与 Application Service 单例同源（共用 ``_harness_manager``），
    CLI/Wire/HTTP 由此共享同一执行内核。
    """
    global _wire_engine
    if _wire_engine is None:
        from .service import get_application_service

        _wire_engine = get_application_service(manager=_harness_manager).engine
        # G1: 引擎领域状态变更（plan/artifact）→ plan/state、artifact/state 通知。
        # 挂接一次（同步契约）；CLI client 挂的是自己的 emitter。
        _wire_engine.state_emitter = _emit_plan_artifact_state
        # G1b: 模型工具（plan_propose 等）经 accessor 取引擎。
        from electromind.engine.accessor import set_engine

        set_engine(_wire_engine)
    return _wire_engine


def _emit_plan_artifact_state(thread_id: str, kind: str, payload: dict) -> None:
    """G1: RunEngine 领域状态变更回调 → JSON-RPC 通知（同步）。"""
    method = "plan/state" if kind == "plan" else "artifact/state"
    _emit_jsonrpc(method, {"thread_id": thread_id, **payload})


def _get_broker():
    global _harness_broker
    if _harness_broker is None:
        from electromind.harness.protocol_v2 import EventBroker

        _harness_broker = EventBroker()
    return _harness_broker


def _get_idempotency():
    global _harness_idempotency
    if _harness_idempotency is None:
        from electromind.harness.protocol_v2 import IdempotencyStore

        _harness_idempotency = IdempotencyStore()
    return _harness_idempotency


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
    "execution_mode",
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


def _command_from_arguments(name: str, arguments: str) -> str:
    """从工具参数提取 command（run_command 的审批风险需要）。"""
    if name != "run_command":
        return ""
    try:
        parsed = json.loads(arguments)
        return str(parsed.get("command", "")) if isinstance(parsed, dict) else ""
    except (json.JSONDecodeError, TypeError):
        return ""


def _arguments_digest(arguments: str) -> str:
    """审批时的参数摘要（sha256 of sorted JSON）。"""
    import hashlib

    try:
        normalized = json.dumps(
            json.loads(arguments), ensure_ascii=False, sort_keys=True
        )
    except (json.JSONDecodeError, TypeError):
        normalized = str(arguments)
    return hashlib.sha256(normalized.encode()).hexdigest()


def _approval_expires_at(*, ttl_seconds: int = 300) -> str:
    """审批 TTL 过期时间（ISO 8601 UTC）。"""
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()


async def emit_permit_request(
    event: ToolCallBegin,
    *,
    thread_id: str = "",
    run_id: str = "",
    approval_id: str = "",
) -> bool:
    """需审批的工具：在 ToolCallBegin 之后补发一条带 Thread/Run Scope 的审批请求。

    这不是 core Event，而是 wire 层的控制事件，仍套用 JSON-RPC notification 形状。
    包含 ``approval_id``、``thread_id`` 和 ``run_id``，使前端可以执行跨 Run
    和跨 Thread 的过期判断与作用域隔离。

    Harness Spine: 审批在发出前注册到 ``ThreadSessionManager.pending_approvals``，
    ``resolve_approval`` 在 permit/deny 时校验四元组绑定。注册失败时不发送
    PermitRequest（不向客户端发布不可操作的审批）。

    Returns True if the PermitRequest was emitted.
    """
    from electromind.harness.identity import new_approval_id
    from electromind.harness.workspace import ApprovalRequest

    aid = approval_id or new_approval_id()
    # Empty thread_id/run_id cannot be registered — do not publish an
    # approval that could never be resolved (fail-closed).
    if not thread_id or not run_id:
        log("[wire] permit request skipped: missing thread/run scope")
        return False
    # Execution context for the approval card (target, workdir, risk)
    workdir = ""
    target = ""
    sandbox = getattr(event, "_sandbox", None)
    if sandbox is None:
        # Look up the runner's sandbox via the harness session
        session = _harness_manager.get_session(thread_id)
        if session is not None:
            sandbox = getattr(getattr(session, "runner", None), "sandbox", None)
    if sandbox is not None:
        workdir = getattr(sandbox, "workdir", "") or ""
        backend = getattr(sandbox, "backend", None)
        target = getattr(backend, "name", "") or ""
        if not target:
            from electromind.sandbox import backend_type_name

            target = backend_type_name(backend) or ""
    # P0-4: 风险由 RiskPolicy 静态表计算（不再硬编码两个工具名）；
    # 审批带参数摘要（执行时校验参数未被篡改）与 TTL 过期时间。
    from electromind.execution.permissions import ActionSpec, risk_of_action

    arguments_text = (
        event.arguments if isinstance(event.arguments, str) else str(event.arguments)
    )
    action = ActionSpec(
        tool=event.name,
        command=_command_from_arguments(event.name, arguments_text),
        target=target,
        workdir=workdir,
        risk=risk_of_action(
            ActionSpec(
                tool=event.name,
                command=_command_from_arguments(event.name, arguments_text),
            )
        ),
    )
    risk = str(action.risk)
    arguments_digest = _arguments_digest(arguments_text)
    expires_at = _approval_expires_at()
    # action_id identifies the concrete action within the tool call.
    # Stable per tool_call_id, distinct from the approval identity.
    action_id = f"action:{event.tool_call_id}"
    approval = ApprovalRequest(
        approval_id=aid,
        thread_id=thread_id,
        run_id=run_id,
        tool_call_id=event.tool_call_id,
        action_id=action_id,
        target=target,
        workdir=workdir,
        risk=risk,
        summary=summarize_tool_args(event.name, event.arguments),
        expires_at=expires_at,
        arguments_digest=arguments_digest,
    )
    registered = await _harness_manager.add_approval(thread_id, approval)
    if not registered:
        log(f"[wire] permit request not registered for {thread_id}")
        return False
    # Gate 2: persist pending approvals so they survive a restart
    _persist_thread_state(thread_id)
    payload = {
        "jsonrpc": "2.0",
        "method": "PermitRequest",
        "params": {
            "tool_call_id": event.tool_call_id,
            "action_id": action_id,
            "approval_id": aid,
            "name": event.name,
            "summary": summarize_tool_args(event.name, event.arguments),
            "thread_id": thread_id,
            "run_id": run_id,
            "target": target,
            "workdir": workdir,
            "risk": risk,
        },
    }
    emit_line(json.dumps(payload, ensure_ascii=False) + "\n")
    return True


# ── Harness Spine wire helpers ─────────────────────────────────────────


async def _approval_scope_valid(
    runner,
    tool_call_id: str,
    approval_id: str,
    thread_id: str,
    run_id: str,
    *,
    approved: bool,
) -> bool:
    """Validate that an approval resolution belongs to the current thread/run.

    Fail-closed: the approval must be registered in the harness session's
    ``pending_approvals``, must still be resolvable, and its bound
    tool_call_id must match.  Resolving consumes the approval so stale
    approvals cannot be replayed.
    """
    if not (isinstance(approval_id, str) and approval_id):
        return False, None  # Fail-closed: scope is mandatory
    if not isinstance(thread_id, str) or not thread_id:
        return False, None
    if not isinstance(run_id, str) or not run_id:
        return False, None
    # Current thread must match
    runner_thread = getattr(getattr(runner, "thread", None), "id", "")
    if runner_thread and runner_thread != thread_id:
        return False, None
    # Resolve through the harness — verifies approval exists, is pending,
    # belongs to the active run, and binds the same tool_call_id, then
    # atomically consumes it (validate-then-consume inside the lock).
    resolved = await _harness_manager.resolve_approval(
        thread_id,
        run_id,
        approval_id,
        approved,
        tool_call_id=tool_call_id,
    )
    if resolved is not None:
        _persist_thread_state(thread_id)  # Gate 2: consumed approval
    return resolved is not None, resolved


class MutationSnapshotError(Exception):
    """A snapshot could not be captured for a reason OTHER than absence
    (SSH down, permission error, path is a directory...).  The mutation
    must NOT be presented as an exact diff."""


def _mutation_target(name: str, arguments: str, runner) -> tuple[str, str] | None:
    """Resolve the ACTUAL mutation target: (source, path).

    ``source`` is ``"sandbox"`` (execution backend, read via the sandbox
    files API) or ``"host"`` (host filesystem, e.g. copy_to_host
    artifacts).  The two namespaces are never mixed.

    - write_file / str_replace: sandbox path.
    - copy_from_host: sandbox ``dest``/basename(host_path) — the real
      target is dest + file name, not dest itself.
    - copy_to_host: HOST ``artifacts/<source basename>``.
    """
    if not isinstance(arguments, str):
        return None
    try:
        payload = json.loads(arguments)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None

    if name in ("write_file", "str_replace"):
        value = payload.get("path")
        if isinstance(value, str) and value.strip():
            return ("sandbox", value.strip())
        return None

    if name == "copy_from_host":
        host_path = payload.get("host_path")
        host_name = (
            host_path.strip().split("/")[-1]
            if isinstance(host_path, str) and host_path.strip()
            else ""
        )
        dest = payload.get("dest")
        if isinstance(dest, str) and dest.strip() and dest.strip() != ".":
            # Real target is dest/basename(host_path), not dest itself
            if host_name:
                return ("sandbox", f"{dest.strip().rstrip('/')}/{host_name}")
            return ("sandbox", dest.strip())
        if host_name:
            return ("sandbox", host_name)
        return None

    if name == "copy_to_host":
        source = payload.get("source")
        if isinstance(source, str) and source.strip():
            sandbox = getattr(runner, "sandbox", None)
            artifacts = getattr(sandbox, "ARTIFACTS_DIRNAME", "artifacts")
            return ("host", f"{artifacts}/{source.strip().split('/')[-1]}")
        return None

    return None


async def _capture_snapshot(source: str, path: str, sandbox, blob_store=None):
    """Source-aware FileSnapshot capture.

    - ``sandbox`` source: read via the sandbox files API (SFTP for SSH,
      local for local) — the snapshot reflects the REAL backend.
    - ``host`` source: read from the host filesystem under host_root.

    Only a DEFINITE absence (file not found) yields ``exists=False``;
    any other failure (SSH down, permission error, directory read)
    raises ``MutationSnapshotError`` so the caller marks the delta
    inexact instead of fabricating a "create" diff.
    """
    from electromind.harness.mutations import FileSnapshot

    if source == "sandbox":
        files = getattr(sandbox, "files", None)
        read = getattr(files, "read", None)
        if read is None:
            raise MutationSnapshotError("sandbox has no files API")
        try:
            data = await read(path)
            return FileSnapshot.from_bytes(data, path, blob_store=blob_store)
        except FileNotFoundError:
            return FileSnapshot(exists=False, size=0, sha256="", content=None)
        except Exception as exc:
            raise MutationSnapshotError(f"snapshot read failed: {exc}") from exc

    # host source
    from pathlib import Path

    host_root = getattr(sandbox, "host_root", None)
    if not host_root:
        raise MutationSnapshotError("sandbox has no host_root")
    local = Path(host_root) / path
    try:
        return FileSnapshot.capture(local, blob_store=blob_store)
    except FileNotFoundError:
        return FileSnapshot(exists=False, size=0, sha256="", content=None)
    except OSError as exc:
        raise MutationSnapshotError(f"host snapshot read failed: {exc}") from exc


def _tool_write_path(name: str, arguments: str) -> str:
    """Extract the target path from a write-tool call's arguments."""
    if not isinstance(arguments, str):
        return ""
    try:
        payload = json.loads(arguments)
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    for key in ("path", "host_path", "source"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _tool_change_counts(name: str, arguments: str) -> tuple[int, int]:
    """Estimate additions/deletions from a write-tool call's arguments.

    - write_file: content lines replace the file (additions = lines).
    - str_replace: old_string removed, new_string added.
    - copy_to_host / copy_from_host: unknown — 0/0.
    """
    if not isinstance(arguments, str):
        return (0, 0)
    try:
        payload = json.loads(arguments)
    except json.JSONDecodeError:
        return (0, 0)
    if not isinstance(payload, dict):
        return (0, 0)

    def count(value: object) -> int:
        if not isinstance(value, str):
            return 0
        return max(1, value.count("\n") + 1)

    if name == "write_file":
        return (count(payload.get("content", "")), 0)
    if name == "str_replace":
        return (
            count(payload.get("new_string", "")),
            count(payload.get("old_string", "")),
        )
    return (0, 0)


def _tool_change_hunks(name: str, arguments: str) -> list[dict]:
    """Build REAL diff hunks (with source text) from a write-tool call.

    The tool arguments carry the actual old/new text, so the hunks are
    evidence of the change, not line-count placeholders:
    - write_file: additions = content lines (deletions unknown — old file
      content is not available post-write).
    - str_replace: deletions = old_string lines, additions = new_string lines.
    """
    if not isinstance(arguments, str):
        return []
    try:
        payload = json.loads(arguments)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []

    def lines(value: object) -> list[str]:
        if not isinstance(value, str):
            return []
        return value.split("\n")

    additions: list[str] = []
    deletions: list[str] = []
    if name == "write_file":
        additions = lines(payload.get("content", ""))
    elif name == "str_replace":
        deletions = lines(payload.get("old_string", ""))
        additions = lines(payload.get("new_string", ""))
    else:
        return []

    if not additions and not deletions:
        return []
    hunk_lines: list[dict] = [
        {"kind": "deletion", "content": line} for line in deletions
    ] + [{"kind": "addition", "content": line} for line in additions]
    # Correct unified-diff coordinates: -old_start,old_count +new_start,new_count
    old_count = len(deletions) or 1
    new_count = len(additions) or 1
    return [
        {
            "header": f"@@ -1,{old_count} +1,{new_count} @@",
            "lines": hunk_lines,
        }
    ]


def _record_idempotent(request_id: str, cmd: str, result: dict | None = None) -> None:
    """Record a successfully completed command for idempotent replay."""
    if not (isinstance(request_id, str) and request_id):
        return
    store = _get_idempotency()
    if not store.is_duplicate(request_id):
        store.record(request_id, result or {"replay": True, "cmd": cmd})


def _emit_input_state_ack(
    message_id: str,
    thread_id: str,
    state: str,
    *,
    detail: str = "",
    target_run_id: str | None = None,
    request_id: str = "",
) -> None:
    """Emit an ``input/state`` ACK event to the client.

    This is the Harness Spine counterpart to the old silent-input behavior.
    Every input now produces an observable state transition.
    ``request_id``（客户端幂等标识）原样回显，供 ServiceAgentClient 关联请求。
    """
    params: dict = {
        "message_id": message_id,
        "thread_id": thread_id,
        "state": state,
    }
    if request_id:
        params["request_id"] = request_id
    if detail:
        params["detail"] = detail
    if target_run_id:
        params["target_run_id"] = target_run_id
    _emit_jsonrpc("input/state", params)


def _emit_model_resolved(
    config,
    requested_mode,
    thread_id,
    *,
    phase: str = "plan",
) -> None:
    """P3: 广播 Run 的模型解析结果（policy / 实际模型 / 原因 / 阶段）。

    Run 开始时解析一次并广播；客户端据此显示 "Auto · <模型>" 与审计原因。
    phase: hybrid plan-execute 的阶段（plan→best / execute→balanced）。
    """
    from electromind.model_resolver import (
        parse_model_policy,
        policy_label,
        resolve_model,
    )

    mode = (
        str(requested_mode.value)
        if requested_mode is not None
        else (config.session_mode or "agent")
    )
    if mode == "run":
        mode = "agent"
    policy = parse_model_policy(config.model)
    try:
        res = resolve_model(policy, session_mode=mode, phase=phase)  # type: ignore[arg-type]
    except (Exception, SystemExit):  # noqa: BLE001 — 解析失败给可读降级
        res = None
    _emit_jsonrpc(
        "model/resolved",
        {
            "thread_id": thread_id,
            "model_policy": policy_label(policy),
            "effective_model": res.effective_model if res is not None else config.resolved_model(),
            "reason": res.reason if res is not None else "resolve-failed",
            "phase": phase,
        },
    )


def _emit_jsonrpc(method: str, params: dict) -> None:
    """Emit a JSON-RPC 2.0 notification with the given method and params.

    Protocol v2: every event goes through the EventBroker for per-thread
    seq, event_id, and snapshot buffering, and carries ``protocol_version``
    and ``timestamp`` (part of the event envelope contract).
    """
    from datetime import datetime, timezone

    thread_id = str(params.get("thread_id", ""))
    if thread_id:
        from electromind.harness.protocol_v2 import EventEnvelope

        run_id = str(params.get("run_id", "") or "")
        item_id = str(params.get("item_id", "") or "")
        envelope = EventEnvelope.create(
            thread_id,
            method,
            params,
            run_id=run_id if run_id else None,
            item_id=item_id if item_id else None,
        )
        tracked = _get_broker().emit(envelope)
        params["seq"] = tracked.seq
        params["event_id"] = tracked.event_id
        params["protocol_version"] = tracked.protocol_version
        params["timestamp"] = tracked.timestamp
    else:
        params.setdefault("protocol_version", 2)
        params.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
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


def emit_execution_state(runner) -> None:
    """下发当前执行模式解析结果，供前端渲染状态栏。"""
    execution = getattr(runner, "_execution", None)
    if execution is None:
        return
    try:
        params = execution.to_dict()
    except (TypeError, AttributeError):
        return
    params["thread_id"] = runner.thread.id
    payload = {
        "jsonrpc": "2.0",
        "method": "ExecutionState",
        "params": params,
    }
    try:
        emit_line(json.dumps(payload, ensure_ascii=False) + "\n")
    except TypeError:
        pass


def emit_execution_state_cleared() -> None:
    """清除执行状态（Resume 时先清空，待新 Runner 打开后重新发送）。"""
    emit_line(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "ExecutionState",
                "params": {
                    "mode": None,
                    "resolved_backend": None,
                    "isolated": False,
                    "warning": None,
                    "diagnostics": [],
                    "thread_id": None,
                },
            }
        )
        + "\n"
    )


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
    from electromind.sandbox import backend_type_name

    return backend_type_name(runner.sandbox.backend)


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


def _skills_service():
    """Shared catalog service — CLI/Desktop/Service use one catalog (SKILL-6)."""
    from electromind.skills.catalog_service import get_shared_catalog_service

    return get_shared_catalog_service()


def _skills_catalog_payload(catalog, *, thread_id: str = "") -> dict:
    """Serialize a ``MultiCandidateCatalog`` for the wire (metadata only)."""
    return {
        "thread_id": thread_id,
        "generation": catalog.generation,
        "catalog_digest": catalog.catalog_digest,
        "cwd": catalog.cwd,
        "repo_root": catalog.repo_root,
        "source_fingerprints": dict(catalog.source_fingerprints),
        "skills": [
            {
                "skill_id": c.skill_id,
                "name": c.descriptor.name,
                "description": c.descriptor.description,
                "scope": c.source.scope,
                "dialect": c.source.dialect,
                "enabled_state": c.enabled_state,
                "trust_state": c.trust_state,
                "content_digest": c.descriptor.content_digest,
            }
            for c in catalog.candidates
        ],
    }


def _emit_skills_catalog(command: dict) -> None:
    """``skills/list`` — the full candidate catalog (picker view)."""
    service = _skills_service()
    catalog = service.list()
    thread_id = str(command.get("thread_id", ""))
    _emit_jsonrpc(
        "skills/list",
        _skills_catalog_payload(catalog, thread_id=thread_id),
    )


def _emit_skills_get(command: dict) -> None:
    """``skills/get`` — one candidate by qualified id."""
    skill_id = str(command.get("skill_id", "")).strip()
    service = _skills_service()
    candidate = service.get(skill_id) if skill_id else None
    _emit_jsonrpc(
        "skills/get",
        {
            "skill_id": skill_id,
            "found": candidate is not None,
            "candidate": (
                {
                    "skill_id": candidate.skill_id,
                    "name": candidate.descriptor.name,
                    "description": candidate.descriptor.description,
                    "scope": candidate.source.scope,
                    "dialect": candidate.source.dialect,
                    "enabled_state": candidate.enabled_state,
                    "trust_state": candidate.trust_state,
                }
                if candidate is not None
                else None
            ),
        },
    )


def _emit_skills_reload(command: dict) -> None:
    """``skills/reload`` — re-discover; bump generation on content change."""
    service = _skills_service()
    log(
        f"[dbg-reload] pre gen={service.list().generation} fp={ {k: v[:8] for k, v in getattr(service, '_source_fingerprints', {}).items()} }"
    )
    catalog = service.reload()
    log(f"[dbg-reload] post gen={catalog.generation}")
    thread_id = str(command.get("thread_id", ""))
    _emit_jsonrpc(
        "skills/reload",
        _skills_catalog_payload(catalog, thread_id=thread_id),
    )


def _emit_skills_changed(command: dict) -> None:
    """``skills/changed`` — fingerprint-based change detection (no bump)."""
    service = _skills_service()
    changed = service.changed()
    thread_id = str(command.get("thread_id", ""))
    _emit_jsonrpc(
        "skills/changed",
        {"thread_id": thread_id, "changed": changed},
    )


async def _emit_skills_install(command: dict) -> None:
    """``skills/install`` — 用户显式安装 Skill（git URL 或本地目录）。

    Desktop Skills Manager 入口；与 CLI ``skills add`` 同语义：
    识别来源 → 安装 → （可选）授予信任 → 刷新目录。
    """
    from pathlib import Path

    from electromind.skills.installer import InstallError, SkillInstaller

    source = str(command.get("source", "")).strip()
    ref = str(command.get("ref", "") or "HEAD")
    path = str(command.get("path", "") or "")
    grant_trust = bool(command.get("trust", False))
    if not source:
        emit_error(
            "skills/install 需要 source 字段（git URL 或本地目录）",
            where="skills/install",
        )
        return
    installer = SkillInstaller()
    try:
        info = await installer.identify_source(source, ref=ref, path=path or None)
        name = str(info["name"])
        # 同名冲突不静默覆盖：已安装同名 Skill 且来源不同 → 拒绝
        # （同来源重装 = 更新语义，放行）。与 CLI preflight 一致。
        same_name = [r for r in installer.installed() if r.name == name]
        if same_name:
            existing = same_name[0]
            new_source = source if info["is_git"] else str(Path(source).resolve())
            if existing.source != new_source:
                emit_error(
                    f"skills/install 失败: 同名 Skill「{name}」已存在"
                    f"（来源 {existing.source}），拒绝覆盖；请先移除或用 update",
                    where="skills/install",
                )
                try:
                    _emit_skills_catalog(command)
                except Exception:  # noqa: BLE001
                    pass
                return
        if info["is_git"]:
            result = await installer.install_from_git(
                source, ref=ref, path=path or None
            )
        else:
            result = await installer.install_from_dir(Path(source))
        if grant_trust:
            installer.set_trust(name, True)
        _emit_jsonrpc(
            "skills/install",
            {
                "ok": True,
                "name": name,
                "target": str(result.target),
                "commit": str(info.get("commit_sha", ""))[:12],
                "trusted": grant_trust,
            },
        )
    except InstallError as exc:
        emit_error(f"skills/install 失败: {exc}", where="skills/install")
    except Exception as exc:  # noqa: BLE001 — 未知安装错误也要可诊断
        emit_error(f"skills/install 异常: {exc}", where="skills/install")
    # 安装成功/失败都刷新目录（wire 流按序处理，随后的 skills/reload 已排队）
    try:
        _emit_skills_catalog(command)
    except Exception:  # noqa: BLE001
        pass


async def _emit_skills_update(command: dict) -> None:
    """``skills/update`` — 从记录来源重新安装并刷新。"""

    from electromind.skills.installer import InstallError, SkillInstaller

    name = str(command.get("name", "")).strip()
    if not name:
        emit_error("skills/update 需要 name 字段", where="skills/update")
        return
    installer = SkillInstaller()
    try:
        result = await installer.update(name)
        _emit_jsonrpc(
            "skills/update",
            {"ok": True, "name": name, "target": str(result.target) if result else ""},
        )
    except InstallError as exc:
        emit_error(f"skills/update 失败: {exc}", where="skills/update")
    except Exception as exc:  # noqa: BLE001
        emit_error(f"skills/update 异常: {exc}", where="skills/update")
    try:
        _emit_skills_catalog(command)
    except Exception:  # noqa: BLE001
        pass


async def _emit_skills_remove(command: dict) -> None:
    """``skills/remove`` — 卸载 installer 管理的 Skill。"""

    from electromind.skills.installer import SkillInstaller

    name = str(command.get("name", "")).strip()
    if not name:
        emit_error("skills/remove 需要 name 字段", where="skills/remove")
        return
    removed = await SkillInstaller().uninstall(name)
    _emit_jsonrpc(
        "skills/remove",
        {"ok": bool(removed), "name": name, "removed": bool(removed)},
    )
    try:
        _emit_skills_catalog(command)
    except Exception:  # noqa: BLE001
        pass


async def _emit_skills_trust(command: dict) -> None:
    """``skills/trust`` — 授予/撤销已安装 Skill 的信任。"""
    from electromind.skills.installer import SkillInstaller

    name = str(command.get("name", "")).strip()
    granted = bool(command.get("granted", False))
    if not name:
        emit_error("skills/trust 需要 name 字段", where="skills/trust")
        return
    changed = SkillInstaller().set_trust(name, granted)
    _emit_jsonrpc(
        "skills/trust",
        {"ok": changed, "name": name, "granted": granted, "changed": changed},
    )
    try:
        _emit_skills_catalog(command)
    except Exception:  # noqa: BLE001
        pass


def emit_skills(runner) -> None:
    """下发当前会话的 skill 目录快照，供前端渲染技能面板。

    优先使用 ``SkillRuntime.state_payload()`` 产出结构化状态（含
    可用/已加载/诊断三分区）；fallback 到旧的 ``runner.skills.list()``。
    """
    skill_runtime = getattr(runner, "skill_runtime", None)
    if skill_runtime is not None:
        payload = skill_runtime.state_payload(
            thread_id=getattr(runner.thread, "id", "")
        )
    else:
        skills = runner.skills.list() if runner else []
        payload = {
            "thread_id": getattr(runner.thread, "id", "") if runner else "",
            "fingerprint": "",
            "skills": [
                {
                    "name": s.name,
                    "description": s.description,
                    "source": "",
                    "sha256": getattr(s, "sha256", ""),
                    "status": "available",
                }
                for s in skills
            ],
            "loaded": [],
            "diagnostics": [],
        }
    emit_line(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "SkillsState",
                "params": payload,
            },
            ensure_ascii=False,
        )
        + "\n"
    )


def emit_execution_context(runner) -> None:
    """Emit SSH execution context state for desktop UI rendering.

    Reads execution documents and diagnostics from the sandbox
    backend.  When no context is present, emits a clear event so
    the renderer can hide stale data from a previous session.
    """
    sandbox = getattr(runner, "sandbox", None)
    if sandbox is None:
        _emit_execution_context_clear(runner)
        return
    backend = getattr(sandbox, "backend", None)
    if backend is None:
        _emit_execution_context_clear(runner)
        return

    try:
        btype = _backend_type_name(backend)
    except Exception:
        _emit_execution_context_clear(runner)
        return
    if btype not in ("ssh", "docker", "podman", "local"):
        _emit_execution_context_clear(runner)
        return

    docs = getattr(backend, "execution_documents", ()) or ()
    diags = getattr(backend, "context_diagnostics", ()) or ()
    if not docs and not diags:
        _emit_execution_context_clear(runner)
        return

    # Build profile_id from docs or fall back to backend type
    profile_id = ""
    for doc in docs:
        pid = getattr(doc, "profile_id", "")
        if pid:
            profile_id = pid
            break

    # Build document summaries with size field for frontend
    doc_summaries = []
    for doc in docs:
        try:
            content = getattr(doc, "content", "")
            doc_summaries.append(
                {
                    "remote_path": getattr(doc, "remote_path", ""),
                    "sha256": getattr(doc, "sha256", ""),
                    "size": len(content),
                    "fetched_at": getattr(doc, "fetched_at", 0.0),
                }
            )
        except Exception:
            continue

    try:
        emit_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "ExecutionContextState",
                    "params": {
                        "type": "ExecutionContextState",
                        "thread_id": getattr(runner.thread, "id", ""),
                        "target": btype,
                        "profile_id": profile_id or btype,
                        "documents": doc_summaries,
                        "diagnostics": list(diags),
                    },
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    except TypeError:
        pass


def _emit_execution_context_clear(runner) -> None:
    """Emit a cleared ExecutionContextState so the renderer hides stale data."""
    thread_id = ""
    if runner is not None:
        thread_id = getattr(runner.thread, "id", "")
    try:
        emit_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "ExecutionContextState",
                    "params": {
                        "type": "ExecutionContextState",
                        "thread_id": thread_id,
                        "target": "",
                        "profile_id": "",
                        "documents": [],
                        "diagnostics": [],
                    },
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    except TypeError:
        pass


def _backend_type_name(backend) -> str:
    """Return the backend type name without importing from electromind."""
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
    return class_name.lower()


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


async def build_sandbox_tree(
    runner,
    virtual_path: str,
    prefix: str = "",
    visited: "set[str] | None" = None,
) -> list[dict]:
    """Recursively list the sandbox workdir tree.

    Uses a ``visited`` set of normalized paths to prevent infinite
    recursion from symlink cycles created by the agent.
    """
    if visited is None:
        visited = set()
    norm = posixpath.normpath(virtual_path)
    if norm in visited:
        return []
    visited.add(norm)

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
            children = await build_sandbox_tree(runner, child_path, node_id, visited)
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

    # Runner-dependent commands: require an open runner.  When none is
    # available (slash intercepted before runner creation), report the
    # gap instead of crashing.
    if runner is None:
        emit_slash_result(name, f"/{name} 需要先打开会话", ok=False)
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


def _encode_and_emit_event(thread_id, run_id, event, seq, state) -> None:
    """M1: 事件统一编码输出（broker seq/event_id + emit_line）。"""

    if thread_id:
        from electromind.harness.protocol_v2 import EventEnvelope

        line = encode_event_line(event)
        try:
            parsed = json.loads(line)
            params = parsed.get("params", {}) if isinstance(parsed, dict) else {}
            method = (
                parsed.get("method", "event") if isinstance(parsed, dict) else "event"
            )
        except (json.JSONDecodeError, TypeError):
            params = {}
            method = "event"
        # Item events carry a stable item_id (Gate 1, 六-3)
        item_id = None
        if method in ("ToolCallBegin", "ToolResult"):
            tc = str(params.get("tool_call_id", "") if isinstance(params, dict) else "")
            if tc:
                item_id = f"item-{tc}"
        elif method in ("TextDelta", "ReasoningDelta"):
            item_ids: dict = state.setdefault("_item_ids", {})
            cur = item_ids.get(thread_id)
            if cur is None:
                item_ids[thread_id] = cur = (
                    f"item-{thread_id}-{len(item_ids) + 1}-{run_id or 'run'}"
                )
            item_id = cur
        elif method == "RunEnd":
            state.get("_item_ids", {}).pop(thread_id, None)
        envelope = EventEnvelope.create(
            thread_id,
            str(method),
            params if isinstance(params, dict) else {},
            run_id=run_id,
            item_id=item_id,
        )
        tracked = _get_broker().emit(envelope)
        if isinstance(params, dict):
            params["thread_id"] = tracked.thread_id
            params["seq"] = tracked.seq
            params["event_id"] = tracked.event_id
            params["protocol_version"] = tracked.protocol_version
            params["timestamp"] = tracked.timestamp
            if tracked.run_id:
                params["run_id"] = tracked.run_id
            if tracked.item_id:
                params["item_id"] = tracked.item_id
        if isinstance(parsed, dict):
            parsed["params"] = params
            line = json.dumps(parsed, ensure_ascii=False) + "\n"
        emit_line(line)
    else:
        emit_line(encode_event_line(event))


async def run_user_turn(
    runner,
    text: str,
    config: ReplConfig,
    state: dict,
    *,
    requested_mode: object | None = None,
) -> None:
    """跑一轮 Agent，事件逐行透传 stdout；需审批工具补发 PermitRequest。

    After the turn ends, queued inputs for the same thread are automatically
    started (chain: complete → dequeue → start next turn).
    """
    ask_permit = not config.permission_auto()
    last_usage: dict | None = None
    thread_id = getattr(runner.thread, "id", "")
    run_id: str | None = None  # Set per-event inside the loop

    # ── P3: Run 开始时解析一次 Auto Model，并把解析结果广播给客户端。
    # Run 开始后不因普通重试切换（解析结果已冻结在 RunSnapshot）。
    try:

        _emit_model_resolved(config, requested_mode, thread_id, phase="plan")
    except (Exception, SystemExit):  # noqa: BLE001 — 解析失败不阻断本轮
        log("[wire] model/resolved emission failed (non-fatal)")
    success = False
    stop_reason: str | None = None  # Terminal stop reason from the runner
    cancelled = False  # Explicit user/task cancellation
    restore_subagent_observer = install_subagent_observer(runner, state)
    # The UI's requested mode (ask/plan) must change the ACTUAL execution
    # capability, not just the snapshot — restore at Run end.
    restore_sandbox_mode = _apply_requested_sandbox_mode(runner, requested_mode)
    # FileMutationInterceptor: capture before/after state at the tool
    # dispatch boundary (not external hooks).  Trackers are PER-THREAD
    # (parallel threads never share baseline state).
    from electromind.harness.mutations import (
        WRITE_TOOLS,
        MutationBlobStore,
        MutationTracker,
    )

    trackers: dict = state.setdefault("_mutation_trackers", {})
    blobs: dict = state.setdefault("_mutation_blobs", {})
    blob_store = blobs.setdefault(thread_id, MutationBlobStore())
    tracker = trackers.setdefault(thread_id, MutationTracker(blob_store=blob_store))
    tracker.clear()
    blob_store.clear()  # per-Run scope: stale blobs must not accumulate
    orig_execute_tool = getattr(runner, "execute_tool", None)
    if orig_execute_tool is not None:
        from electromind.harness.mutations import FileMutationDelta, FileSnapshot

        async def tracked_execute_tool(tool_call):
            name = getattr(tool_call, "name", "")
            arguments = getattr(tool_call, "arguments", "")
            sandbox = getattr(runner, "sandbox", None)
            target = _mutation_target(name, arguments, runner)
            source, snapshot_path = target if target else ("", None)
            capture_failed = False

            async def safe_capture():
                nonlocal capture_failed
                if not snapshot_path:
                    return None
                try:
                    return await _capture_snapshot(
                        source, snapshot_path, sandbox, blob_store
                    )
                except MutationSnapshotError:
                    # Read error (SSH down, permission...) — we cannot
                    # produce a trustworthy diff, BUT the mutation must
                    # not vanish: the call is recorded as INEXACT below.
                    capture_failed = True
                    return None

            absent = FileSnapshot(exists=False, size=0, sha256="", content=None)
            before = await safe_capture()
            try:
                output = await orig_execute_tool(tool_call)
            except BaseException:
                # The tool FAILED but may have partially modified the disk
                # (truncate-then-write etc.).  Capture the after state and
                # record an INEXACT delta — the mutation must never be
                # silently unrecorded (fail-closed, not fail-blind).
                if name in WRITE_TOOLS and snapshot_path:
                    after = await safe_capture()
                    tracker.track(
                        FileMutationDelta(
                            source=source,
                            tool_call_id=str(getattr(tool_call, "id", "")),
                            path=snapshot_path,
                            kind="update",
                            before=before or absent,
                            after=after or absent,
                            exact=False,
                        )
                    )
                raise
            after = await safe_capture()
            if name in WRITE_TOOLS and snapshot_path:
                kind = (
                    "delete"
                    if before is not None
                    and after is not None
                    and before.exists
                    and not after.exists
                    else "create"
                    if before is not None
                    and after is not None
                    and not before.exists
                    and after.exists
                    else "update"
                )
                tracker.track(
                    FileMutationDelta(
                        source=source,
                        tool_call_id=str(getattr(tool_call, "id", "")),
                        path=snapshot_path,
                        kind=kind,
                        before=before or absent,
                        after=after or absent,
                        exact=output.ok and not capture_failed,
                    )
                )
            return output

        runner.execute_tool = tracked_execute_tool
    try:
        from electromind.core.events import RunEnd, TurnResult

        engine = _get_engine()
        engine.register_runner(thread_id, runner)

        def _emit(thread_id_, run_id_, event, seq) -> None:
            nonlocal stop_reason, last_usage, run_id
            if isinstance(event, RunEnd):
                stop_reason = getattr(event, "stop_reason", None)
            if isinstance(event, TurnResult) and event.usage:
                last_usage = event.usage
            if run_id_:
                run_id = run_id_
            _encode_and_emit_event(thread_id_, run_id_, event, seq, state)

        async def _on_approval(thread_id_, run_id_, event) -> None:
            # Unified decision: the SAME policy the runner enforces.
            # auto-safe must not produce ghost approvals for commands
            # the backend auto-approves.
            from .tool_permit import requires_permit_prompt

            if not requires_permit_prompt(config.resolved_permission_mode(), event):
                return
            await emit_permit_request(
                event,
                thread_id=thread_id_,
                run_id=run_id_ or "",
            )

        async def _before_finish(thread_id_, run_id_, outcome) -> None:
            # Settle pending immediates BEFORE the terminal transition
            # (the transition defers anything still pending).
            await _settle_pending_immediates(runner, thread_id_, state, config)

        async def _on_finish(thread_id_, run_id_, outcome) -> None:
            nonlocal success, cancelled
            success = outcome == "completed"
            cancelled = outcome == "cancelled"
            await _wire_after_finish(
                runner, thread_id_, run_id_, outcome, state, config
            )

        outcome = await engine.run_loop(
            thread_id,
            runner,
            text,
            emitter=_emit,
            needs_permit=(
                (lambda ev: ask_permit and needs_tool_permit(ev.name))
                if ask_permit
                else None
            ),
            on_approval=_on_approval,
            before_finish=_before_finish,
            on_finish=_on_finish,
        )
        success = outcome == "completed"
        cancelled = outcome == "cancelled"
    except asyncio.CancelledError:
        # Explicit cancellation (task.cancel()) → CANCELLED, not FAILED
        cancelled = True
        raise
    except Exception as exc:
        log(f"[wire] turn failed: {exc}")
        emit_error(format_exc(exc), where="turn")
    finally:
        restore_subagent_observer()
        restore_sandbox_mode()
        # Restore the original tool dispatch (remove the mutation wrapper)
        if orig_execute_tool is not None:
            runner.execute_tool = orig_execute_tool
        # FLUSH the per-thread net mutations ONCE (N writes → one
        # FileChange per path).  Inexact deltas and no-op changes are
        # filtered — a failed/uncertain write is never shown as a
        # normal "modified" event.
        if thread_id:
            for key in list(tracker._baseline.keys()):
                src, path = key
                net = tracker.net_change(src, path, "")
                if net is None:
                    continue
                before_sha = net.get("before", {}).get("sha256", "")
                after_sha = net.get("after", {}).get("sha256", "")
                if net.get("exact", True) and before_sha == after_sha:
                    continue  # exact no-op — nothing actually changed
                # Inexact (failed/partial) mutations ARE reported — a
                # change may have hit the disk and must be visible — and
                # changes recorded before a failed Run still flush.
                _emit_jsonrpc(
                    "FileChange",
                    {
                        "thread_id": thread_id,
                        "run_id": run_id or "",
                        **net,
                    },
                )
        if last_usage is not None:
            touch_thread_usage(
                runner.thread,
                last_usage,
                context_limit=thread_context_limit(runner.thread),
            )
        # M1: 终端转换 / workspace 释放由 RunEngine._finish_run 统一完成；
        # 这里只负责过期审批事件、turn 清理与 auto-start 链。
        expired = await _harness_manager.take_expired_approvals(thread_id)
        for approval in expired:
            _emit_jsonrpc(
                "approval/resolved",
                {
                    "thread_id": thread_id,
                    "run_id": getattr(approval, "run_id", "") or "",
                    "approval_id": getattr(approval, "approval_id", "") or "",
                    "tool_call_id": getattr(approval, "tool_call_id", "") or "",
                    "status": "expired",
                },
            )
        _set_turn(state, thread_id, None)  # Clear per-thread and legacy turn
        _get_engine().unregister_runner(thread_id)
        # Auto-start next queued input.  Frozen policy: cancel only cancels
        # the CURRENT Run — explicitly queued inputs continue FIFO after ANY
        # terminal end (completed or cancelled).  Failures do NOT auto-start
        # (avoids failure loops).
        run_ended = success or cancelled or stop_reason == "cancelled"
        if run_ended and not _turn_active_for_thread(state, thread_id):
            # Same full creation flow as the first Run (Gate 1, 八 / 一-7;
            # Gate 2, 九): workspace lease → start_run → freeze RunSnapshot
            # → persist the active-run marker BEFORE the turn starts.
            await _auto_start_next(thread_id, runner, config, state)


async def _settle_pending_immediates(
    runner, thread_id: str, state: dict, config
) -> None:
    """M1: 终态转换前 settle 立即输入（语义检查点 pending）。

    未被读取的立即输入 → defer 到队列头（保留原始 identity）；
    已应用的 → applied ACK。两侧都到达终态 receipt。
    """
    ckp = getattr(runner, "inbound_checkpoint", None)
    unread: list[tuple[str, str]] = []
    if ckp is not None:
        pending = ckp.take_pending()
        unread = [(m.message_id, m.text) for m in pending]
    deferred, applied = await _harness_manager.settle_pending_immediate(
        thread_id, unread
    )
    if deferred:
        _harness_manager.restore_queued_at_head(thread_id, deferred)
        for msg in deferred:
            _emit_input_state_ack(
                msg.message_id,
                thread_id,
                "deferred",
                detail="Run ended before the message could be applied",
            )
        log(
            f"[wire] {thread_id} {len(deferred)} unread steer(s) → deferred to next run"
        )
    for msg in applied:
        _emit_input_state_ack(
            msg.message_id,
            thread_id,
            "applied",
            detail="Applied at checkpoint",
        )


async def _wire_after_finish(
    runner, thread_id: str, run_id: str, outcome: str, state: dict, config
) -> None:
    """M1: RunEngine 终态转换后的 wire 收尾（waiter 唤醒 + 持久化）。"""
    # Wake threads waiting on the same workspace: a released lease
    # must never leave a queued waiter waiting forever (Gate 1, 八).
    ws_key = _workspace_key_for(runner)
    if ws_key is not None:
        for wtid in _harness_manager.take_workspace_waiters(ws_key):
            if wtid == thread_id:
                continue
            wsession = _harness_manager.get_session(wtid)
            wrunner = _peek_runner(state, wtid) or getattr(wsession, "runner", None)
            if wrunner is None:
                # Not startable yet — re-register so a LATER
                # release can wake it (never take-and-drop).
                _harness_manager.register_workspace_waiter(wtid, ws_key)
                continue
            if _turn_active_for_thread(state, wtid):
                continue
            await _auto_start_next(wtid, wrunner, config, state)
    _persist_thread_state(thread_id)


def turn_active(state: dict) -> bool:
    """当前是否有一轮 Agent 还在后台跑。"""
    task = state.get("turn")
    return task is not None and not task.done()


def _active_thread_id(state: dict) -> str:
    """Return the currently active thread id from wire state."""
    tid = state.get("thread_id", "")
    return tid if isinstance(tid, str) else ""


async def _auto_start_next(
    thread_id: str, runner, config: ReplConfig, state: dict
) -> bool:
    """Start the next queued input as a new Run — the FULL creation flow
    (Gate 1, 八 / 一-7; Gate 2, 九): workspace lease → start_run → freeze
    RunSnapshot → persist the active-run marker BEFORE the turn starts.

    On a lease conflict the thread is registered as a workspace waiter
    (woken when the holder releases) and False is returned.  Returns True
    when a new turn was spawned.
    """
    import asyncio

    from electromind.harness.identity import new_run_id

    ws_key = _workspace_key_for(runner)
    # The next queued input's requested mode (from the UI) drives the
    # lease decision exactly like the first-Run path.
    peeked = _harness_manager.peek_queued_input(thread_id)
    if peeked is None:
        return False
    session_mode = _resolved_session_mode(
        config, getattr(peeked, "requested_mode", None)
    )
    pre_run_id = new_run_id()
    if ws_key is not None:
        acquired = await _harness_manager.try_acquire_workspace(
            thread_id, ws_key, pre_run_id, session_mode
        )
        if not acquired:
            # Holder still active — leave the input queued and wake us up
            # when the lease is released (never wait forever).
            _harness_manager.register_workspace_waiter(thread_id, ws_key)
            log(f"[wire] {thread_id} waiting for workspace {ws_key}")
            return False
    start_res = await _harness_manager.start_run(thread_id, runner, run_id=pre_run_id)
    if start_res is None:
        await _harness_manager.release_workspace(thread_id, pre_run_id)
        log(f"[wire] auto-start failed for {thread_id}")
        return False
    run_id, queued_msg = start_res
    await _harness_manager.set_run_snapshot(
        thread_id,
        _build_run_snapshot(
            runner,
            config,
            run_id,
            thread_id,
            queued_msg.message_id,
            requested_mode=getattr(queued_msg, "requested_mode", None),
        ),
    )
    _persist_thread_state(thread_id)
    log(f"[wire] auto-starting next queued run on {thread_id}")
    task = asyncio.create_task(
        run_user_turn(
            runner,
            queued_msg.text,
            config,
            state,
            requested_mode=getattr(queued_msg, "requested_mode", None),
        )
    )
    _set_turn(state, thread_id, task)
    _emit_input_state_ack(
        queued_msg.message_id,
        thread_id,
        "applied",
        detail="Auto-started from queue",
    )
    return True


# ── RunSnapshot construction (Gate 1, 一-7) ───────────────────────────


def _build_run_snapshot(
    runner,
    config: ReplConfig,
    run_id: str,
    thread_id: str,
    input_message_id: str,
    *,
    requested_mode=None,
) -> object:
    """Freeze the immutable RunSnapshot at Run creation.

    Captures mode, model, execution target, permission policy, project
    path, skills/tools digests and max iterations.  None of these fields
    change for the lifetime of the Run.
    """
    import hashlib

    from electromind.harness.identity import RunSnapshot
    from electromind.harness.state import (
        ExecutionTargetSnapshot,
        PermissionPolicySnapshot,
        SessionMode,
    )

    mode = requested_mode or _session_mode_for(config)
    model = config.resolved_model()
    max_iterations = config.resolved_max_turns()
    workdir = ""
    kind = "local"
    profile_id = ""
    execution = getattr(runner, "_execution", None)
    if execution is not None:
        resolved_backend = getattr(execution, "resolved_backend", "")
        kind = str(getattr(execution, "mode", "local") or "local")
        if resolved_backend:
            profile_id = str(resolved_backend)
    sandbox = getattr(runner, "sandbox", None)
    if sandbox is not None:
        workdir = getattr(sandbox, "workdir", "") or ""
        if not profile_id:
            profile_id = kind
    if not workdir:
        workdir = runner_project_path(runner) or ""

    def _digest(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16] if text else ""

    # Real digests, not placeholders (Gate 1, 一-7): the BaseRunner keeps
    # the assembled system prompt and tool list on its Agent; the skills
    # digest comes from the SkillRuntime's frozen SkillSetSnapshot.
    system_prompt = ""
    tool_set_digest = ""
    agent = getattr(runner, "agent", None)
    if agent is not None:
        system_prompt = str(getattr(agent, "system", "") or "")
        tools = getattr(agent, "tools", None)
    else:
        tools = None
    if not tools:  # Legacy runners expose tools on the runner itself
        tools = getattr(runner, "tools", None) or getattr(runner, "tool_set", None)
    if tools is not None:
        names = sorted(
            str(getattr(t, "name", "")) for t in tools if getattr(t, "name", "")
        )
        if names:
            tool_set_digest = _digest("\n".join(names))
        else:
            tool_set_digest = _digest(str(tools))
    skill_set_digest = ""
    skill_runtime = getattr(runner, "skill_runtime", None)
    if skill_runtime is not None:
        set_snapshot = getattr(skill_runtime, "_set_snapshot", None)
        digest = getattr(set_snapshot, "digest", "") if set_snapshot is not None else ""
        if digest:
            skill_set_digest = str(digest)
        else:  # Legacy fallback: hash the generation counter
            skill_set_digest = _digest(str(getattr(skill_runtime, "_generation", "")))

    return RunSnapshot(
        run_id=run_id,
        thread_id=thread_id,
        input_message_id=input_message_id,
        session_mode=mode,
        model=model,
        max_iterations=max_iterations,
        execution_target=ExecutionTargetSnapshot(
            target_id=profile_id or kind,
            kind=kind,
            workdir=workdir,
            profile_id=profile_id,
        ),
        permission_policy=PermissionPolicySnapshot(
            auto_approve=config.permission_auto(),
            # Ask/Plan are read-only: no file writes, no command execution.
            # Run mode reflects the resolved permission mode (write-capable
            # either way — prompting is captured by auto_approve).
            allow_file_write=mode == SessionMode.RUN,
            allow_execute=mode == SessionMode.RUN,
        ),
        project_path=runner_project_path(runner),
        system_prompt_digest=_digest(system_prompt),
        skill_set_digest=skill_set_digest,
        tool_set_digest=tool_set_digest,
        created_at=datetime.now().isoformat(),
    )


# ── Workspace lease helpers (Gate 1, 八) ──────────────────────────────


def _canonical_workdir(workdir: str, *, local: bool) -> str:
    """Canonicalize a workdir for lease-keying.

    Local paths are fully resolved (symlinks, ``.``/``..``, tilde) so two
    spellings of the SAME directory map to ONE lease.  Remote/container
    paths cannot be resolved on the host — normalized lexically only.
    """
    import os

    if not workdir:
        return workdir
    if local:
        try:
            return os.path.realpath(os.path.expanduser(workdir))
        except (OSError, ValueError):
            return os.path.normpath(workdir)
    return os.path.normpath(workdir)


def _workspace_key_for(runner):
    """Derive the WorkspaceKey for a Runner's execution target + workdir.

    ``execution target + canonical workdir`` together form the key.  Local
    mode keys on the project path; sandbox/ssh keys on backend + workdir.
    Workdirs are canonicalized so path aliases (``/a`` vs ``/a/.``,
    symlinks, ``~``) cannot bypass the exclusive lease.  Returns None when
    no workdir is known (lease skipped).
    """
    from electromind.harness.identity import WorkspaceKey

    workdir = ""
    target_id = "local"
    sandbox = getattr(runner, "sandbox", None)
    if sandbox is not None:
        workdir = getattr(sandbox, "workdir", "") or ""
        backend = getattr(sandbox, "backend", None)
        if backend is not None:
            try:
                from electromind.sandbox import backend_type_name

                target_id = backend_type_name(backend) or "sandbox"
            except Exception:
                target_id = "sandbox"
    if not workdir:
        workdir = runner_project_path(runner) or ""
    if not workdir:
        return None
    canonical = _canonical_workdir(workdir, local=target_id == "local")
    return WorkspaceKey(
        execution_target_id=target_id,
        canonical_workdir=canonical,
    )


def _session_mode_for(config: ReplConfig):
    """Map ReplConfig to a harness SessionMode.

    ``config.session_mode`` (ask|plan|run) is the primary source; the
    legacy ``command_policy == "ask"`` maps to ASK.  Ask/Plan are
    read-only (never acquire the write lease); Run mode is write-capable
    and must acquire it.
    """
    from electromind.harness.state import SessionMode

    mode = getattr(config, "session_mode", None)
    if isinstance(mode, str) and mode in {"ask", "plan", "run"}:
        return SessionMode(mode)
    if getattr(config, "command_policy", "") == "ask":
        return SessionMode.ASK
    return SessionMode.RUN


def _resolved_session_mode(
    config: ReplConfig, requested_mode: object | None
) -> "object":
    """Resolve the SessionMode for a Run: the UI's per-input requested
    mode wins (it is frozen into the RunSnapshot), else the config's."""
    from electromind.harness.state import SessionMode

    if isinstance(requested_mode, SessionMode):
        return requested_mode
    return _session_mode_for(config)


def _apply_requested_sandbox_mode(runner, requested_mode: object | None):
    """Apply the UI's requested session mode to the RUNNER's sandbox so
    the ACTUAL execution capability (tool guard) matches the RunSnapshot.

    The sandbox re-reads ``spec.session_mode`` on every command/file
    operation, so switching it before the Run starts enforces ask/plan
    read-only semantics even though the runner was opened with the base
    config.  Returns a callable that restores the original mode.
    """
    if requested_mode is None:
        return lambda: None
    sandbox = getattr(runner, "sandbox", None)
    spec = getattr(sandbox, "spec", None)
    if spec is None or not hasattr(spec, "session_mode"):
        return lambda: None
    from electromind.harness.state import SessionMode

    mode = (
        requested_mode
        if isinstance(requested_mode, SessionMode)
        else SessionMode(str(requested_mode))
    )
    # harness ask/plan/run → sandbox ask/plan/agent (sandbox's write mode)
    sandbox_mode = (
        "ask"
        if mode == SessionMode.ASK
        else "plan"
        if mode == SessionMode.PLAN
        else "agent"
    )
    original = spec.session_mode
    if original == sandbox_mode:
        return lambda: None
    spec.session_mode = sandbox_mode
    log(f"[wire] sandbox mode → {sandbox_mode} (requested {mode})")

    def restore() -> None:
        spec.session_mode = original

    return restore


# ── State persistence (Gate 2, 九) ────────────────────────────────────


def _thread_state_path_for(thread_id: str):
    """Return the harness_state.json path for a thread (or None)."""
    from pathlib import Path

    from electromind.harness.persistence import thread_state_path

    try:
        thread = open_thread_history(thread_id)
        root = getattr(thread, "root", None)
        if root is None:
            return None
        return thread_state_path(Path(root))
    except Exception:
        return None


def _persist_thread_state(thread_id: str) -> None:
    """Atomically persist a thread's harness state (queue, immediate,
    approvals, active-run marker, external tasks)."""
    from electromind.harness.persistence import (
        approval_to_dict,
        input_message_to_dict,
        receipt_to_dict,
        save_thread_state,
    )

    path = _thread_state_path_for(thread_id)
    if path is None:
        return
    session = _harness_manager.get_session(thread_id)
    if session is None:
        return
    # Only a LIVE run is persisted as the active-run marker.  A terminal
    # phase (completed/cancelled/failed/interrupted) must NOT be restored
    # as "process died mid-Run" on the next restart — the run finished.
    from electromind.harness.state import is_terminal_run_phase

    marker_run_id = (
        None
        if is_terminal_run_phase(session.active_run_phase)
        else session.active_run_id
    )
    state = {
        "version": 1,
        "active_run_id": marker_run_id,
        "queued_inputs": [
            input_message_to_dict(m) for m in session.queued_inputs.all()
        ],
        "pending_immediate": [
            input_message_to_dict(m) for m in session.pending_immediate
        ],
        "receipt_history": [
            receipt_to_dict(r) for r in session.receipt_history.values()
        ],
        "pending_approvals": [
            approval_to_dict(a) for a in session.pending_approvals.values()
        ],
        # Thread-scoped: never write another thread's task refs (remote
        # ids / resume tokens) into this thread's state file.
        "external_tasks": [
            t.to_dict() for t in _harness_manager.external_tasks.for_thread(thread_id)
        ],
    }
    try:
        save_thread_state(path, state)
    except Exception as exc:
        log(f"[wire] persist {thread_id} failed: {exc}")


async def _recover_thread_states() -> None:
    """Recovery scan at startup (Gate 2, 九).

    For every thread with a persisted harness state:
    - ``active_run_id`` present → the process died mid-Run → mark the Run
      INTERRUPTED (never COMPLETED).
    - ``pending_immediate`` → restored to the HEAD of the queue.
    - ``pending_approvals`` → restored then expired (cannot re-verify the
      tool state after a restart — fail-closed).
    - in-flight external tasks → marked UNKNOWN (no domain adapter to
      re-attach).
    Restoring is idempotent: loading the same file twice yields the same
    result.
    """
    from pathlib import Path

    from electromind.harness.external import ExternalTaskRef
    from electromind.harness.persistence import (
        approval_from_dict,
        input_message_from_dict,
        input_message_to_dict,
        load_thread_state,
        receipt_from_dict,
        receipt_to_dict,
        save_thread_state,
        thread_state_path,
    )

    root = Path(default_threads_root())
    if not root.exists():
        return
    recovered = 0
    for thread_dir in root.iterdir():
        if not thread_dir.is_dir():
            continue
        path = thread_state_path(thread_dir)
        data = load_thread_state(path)
        if data is None:
            continue
        thread_id = thread_dir.name
        active_run_id = data.get("active_run_id") or None
        if active_run_id:
            _harness_manager.restore_session_marker(thread_id, active_run_id)
            await _harness_manager.mark_interrupted(thread_id, active_run_id)
            log(f"[wire] recovery: {thread_id} run {active_run_id} → interrupted")
            recovered += 1
        # Plain queued inputs first (FIFO tail), then deferred immediates
        # at the HEAD — original order is preserved.
        queued_inputs = [
            input_message_from_dict(d)
            for d in data.get("queued_inputs", [])
            if isinstance(d, dict) and d.get("message_id")
        ]
        if queued_inputs:
            _harness_manager.restore_queued_inputs(thread_id, queued_inputs)
            log(f"[wire] recovery: {thread_id} {len(queued_inputs)} queued → tail")
        pending_immediate = [
            input_message_from_dict(d)
            for d in data.get("pending_immediate", [])
            if isinstance(d, dict) and d.get("message_id")
        ]
        if pending_immediate:
            _harness_manager.restore_queued_at_head(thread_id, pending_immediate)
            log(
                f"[wire] recovery: {thread_id} {len(pending_immediate)} immediate → head"
            )
        receipts = [
            receipt_from_dict(d)
            for d in data.get("receipt_history", [])
            if isinstance(d, dict) and d.get("message_id")
        ]
        if receipts:
            _harness_manager.restore_receipt_history(thread_id, receipts)
            log(f"[wire] recovery: {thread_id} {len(receipts)} receipts → history")
        approvals = [
            approval_from_dict(d)
            for d in data.get("pending_approvals", [])
            if isinstance(d, dict) and d.get("approval_id")
        ]
        if approvals:
            _harness_manager.restore_approvals(thread_id, approvals)
            log(f"[wire] recovery: {thread_id} {len(approvals)} approvals → expired")
        tasks = [
            ExternalTaskRef.from_dict(d)
            for d in data.get("external_tasks", [])
            if isinstance(d, dict) and d.get("external_task_id")
        ]
        if tasks:
            _harness_manager.external_tasks.restore(tasks)
            _harness_manager.external_tasks.mark_unverifiable_unknown()
            log(f"[wire] recovery: {thread_id} {len(tasks)} external tasks → unknown")
        # Crash-safe handoff: the restored queues/receipts are now owned
        # by the LIVE manager — persist them back IMMEDIATELY so a second
        # crash (right after this recovery) cannot lose the recovered
        # messages.  The active-run marker stays None (interrupted is
        # terminal); approvals were expired; only the thread's OWN
        # external task refs remain.
        session = _harness_manager.get_session(thread_id)
        if session is not None:
            handoff = {
                "version": 1,
                "active_run_id": None,
                "queued_inputs": [
                    input_message_to_dict(m) for m in session.queued_inputs.all()
                ],
                "pending_immediate": [
                    input_message_to_dict(m) for m in session.pending_immediate
                ],
                "receipt_history": [
                    receipt_to_dict(r) for r in session.receipt_history.values()
                ],
                "pending_approvals": [],
                "external_tasks": [
                    t.to_dict()
                    for t in _harness_manager.external_tasks.for_thread(thread_id)
                ],
            }
            save_thread_state(path, handoff)
    if recovered:
        log(f"[wire] recovery complete: {recovered} interrupted run(s)")


def _turn_active_for_thread(state: dict, thread_id: str) -> bool:
    """Check if a specific thread has an active (running) turn.

    Checks the per-thread ``_turns`` dict first.  Only falls back to the
    legacy ``state["turn"]`` when ``_turns`` is completely empty (backward
    compatibility with old clients that haven't adopted per-thread protocol).
    """
    turns: dict = state.setdefault("_turns", {})
    task = turns.get(thread_id)
    if task is not None:
        return not task.done()
    # Only fall back to legacy when no per-thread turns exist at all.
    # Once any thread is tracked in _turns, the legacy slot is unreliable
    # (it may point to a background thread's task, not the active thread's).
    if not turns:
        legacy = state.get("turn")
        if legacy is not None and not legacy.done():
            return thread_id == _active_thread_id(state)
    return False


def _save_runner(state: dict, thread_id: str, runner) -> None:
    """Store a runner in the per-thread runner registry."""
    if runner is not None and thread_id:
        runners: dict = state.setdefault("_runners", {})
        runners[thread_id] = runner


def _load_runner(state: dict, thread_id: str):
    """Load a runner from the per-thread registry, removing it."""
    runners: dict = state.get("_runners", {})
    return runners.pop(thread_id, None) if runners else None


def _peek_runner(state: dict, thread_id: str):
    """Read a runner from the registry WITHOUT removing it.

    Used by the workspace-waiter wake-up: a conflict re-registers the
    waiter, and the NEXT release must find the runner again (a pop would
    lose it forever after the first conflict).
    """
    runners: dict = state.get("_runners", {})
    return runners.get(thread_id) if runners else None


def _set_turn(state: dict, thread_id: str, task: asyncio.Task | None) -> None:
    """Set the turn task for a thread."""
    turns: dict = state.setdefault("_turns", {})
    if task is None:
        turns.pop(thread_id, None)
    else:
        turns[thread_id] = task
    # Backward compat: also set the legacy "turn" key for the active thread
    if thread_id == _active_thread_id(state):
        state["turn"] = task


def _cancel_thread_turn(state: dict, thread_id: str) -> bool:
    """Cancel the turn for a specific thread. Returns True if a turn was cancelled."""
    turns: dict = state.setdefault("_turns", {})
    task = turns.pop(thread_id, None)
    if task is not None and not task.done():
        task.cancel()
        # Also clear legacy turn if this is the active thread
        if thread_id == _active_thread_id(state):
            state["turn"] = None
        return True
    return False


async def open_fresh_runner(config: ReplConfig, project_path: str | None = None):
    """开一个干净会话：thread_id 置空，让 open_runner 生成新的 thread-<时间戳>。"""
    if project_path is not None:
        config = replace(config, project_path=project_path)
    runner = await open_runner(replace(config, thread_id=None))
    _wire_skill_state_callback(runner)
    return runner


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
    runner = await open_runner(replace(config, thread_id=thread_id))
    _wire_skill_state_callback(runner)
    return runner


def _wire_skill_state_callback(runner) -> None:
    """Set the skill state change callback so use_skill emits updated state."""
    skill_runtime = getattr(runner, "skill_runtime", None)
    if skill_runtime is not None:
        skill_runtime._on_skill_state_change = lambda: emit_skills(runner)


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
    # 如果上一次 reset 失败并保留了 pending_config，沿用用户选择的
    # execution mode 等参数，而不是静默回退到进程启动时的原始配置。
    # 注意：不敢先 pop，否则 open_fresh_runner 再次失败时配置永久丢失，
    # 下一次 ensure_runner 又会回退到默认 sandbox。
    effective_config = state.get("pending_config", config)
    runner = await open_fresh_runner(effective_config)
    # 成功创建后清除 pending_config，避免脏状态残留。
    state.pop("pending_config", None)
    return runner


def emit_empty_history_replay() -> None:
    """前端加载失败/无会话时用空 HistoryReplay 解除骨架屏。"""
    payload = {
        "jsonrpc": "2.0",
        "method": "HistoryReplay",
        "params": {"thread_id": "", "title": "", "project_path": "", "messages": []},
    }
    emit_line(json.dumps(payload, ensure_ascii=False) + "\n")


async def handle_command(command: dict, runner, config: ReplConfig, state: dict):
    """按命令类型分派；返回当前 runner（reset/resume 时可能换成新 runner）。"""
    request_id = command.get("request_id", "")
    cmd = command.get("cmd", "")

    # ── Harness Spine: idempotency ─────────────────────────────────────
    if isinstance(request_id, str) and request_id:
        store = _get_idempotency()
        if store.is_duplicate(request_id):
            stored = store.get_result(request_id)
            log(f"[wire] idempotent replay: {request_id}")
            # Replay the stored ACK payload verbatim
            if isinstance(stored, dict) and stored.get("_ack_method"):
                _emit_jsonrpc(
                    str(stored["_ack_method"]),
                    {k: v for k, v in stored.items() if not k.startswith("_")},
                )
            return runner

    result = await _dispatch_command(command, runner, config, state)

    # Record successful completion for idempotent replay.
    # The _ack_payload is set by command handlers (e.g. input/send) that
    # want their response replayed on retry.
    if isinstance(request_id, str) and request_id:
        ack_payload = command.get("_ack_payload")
        if isinstance(ack_payload, dict):
            _get_idempotency().record(request_id, ack_payload)
        else:
            _get_idempotency().record(request_id, {"replay": True, "cmd": cmd})

    return result


async def _dispatch_command(command: dict, runner, config: ReplConfig, state: dict):
    """命令分派实现。由 handle_command 包装幂等和记录。"""
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

    # ── Skills: unified catalog (SKILL-6) ────────────────────────────────
    if cmd == "skills/list":
        _emit_skills_catalog(command)
        return runner

    if cmd == "skills/get":
        _emit_skills_get(command)
        return runner

    if cmd == "skills/reload":
        _emit_skills_reload(command)
        return runner

    if cmd == "skills/changed":
        _emit_skills_changed(command)
    if cmd == "skills/install":
        await _emit_skills_install(command)
        return runner
    if cmd == "skills/update":
        await _emit_skills_update(command)
        return runner
    if cmd == "skills/remove":
        await _emit_skills_remove(command)
        return runner
    if cmd == "skills/trust":
        await _emit_skills_trust(command)
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
        emit_execution_context(runner)
        return runner

    if cmd == "skills":
        emit_skills(runner)
        return runner

    if cmd == "resume":
        thread_id = command.get("thread_id")
        if not (isinstance(thread_id, str) and thread_id):
            log("[wire] resume missing thread_id")
            return runner
        # Harness Spine: switching threads is ALWAYS allowed — the user
        # may want to view progress or cancel a background thread.
        # The target thread's turn (if any) keeps running independently.
        project_path = command_project_path(command)
        try:
            thread = open_thread_history(thread_id, project_path)
            if thread_is_soft_deleted(thread.load_metainfo()):
                raise ValueError(f"会话已删除：{thread_id}")
        except (Exception, SystemExit) as exc:
            log(f"[wire] resume failed: {exc}")
            emit_empty_history_replay()
            emit_error(format_exc(exc, phase="start"), where="resume")
            return runner
        # Harness Spine: save current runner so background tasks keep running.
        # Switching threads must NOT close the previous runner (principle #1).
        old_thread_id = _active_thread_id(state)
        if runner is not None and old_thread_id and old_thread_id != thread_id:
            _save_runner(state, old_thread_id, runner)
            _harness_manager.get_session(old_thread_id)  # ensure session exists
            log(f"[wire] backgrounding runner for {old_thread_id}")
        # Try to load an already-open runner for the target thread
        cached = _load_runner(state, thread_id)
        state["thread_id"] = thread.id
        state["project_path"] = project_path
        emit_execution_state_cleared()
        emit_thread_history_replay(thread)
        if cached is not None:
            # Target thread already has a live runner — switch to it directly
            log(f"[wire] resumed cached runner for {thread_id}")
            return cached
        return None  # Caller must open a new runner for the target thread

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
            # 保存本次 reset 的配置，避免后续 ensure_runner 回退到
            # 进程启动时的原始配置（例如从 local 切回默认 sandbox）。
            state["pending_config"] = reset_config
            # Thread.open 已落盘，沙箱启动失败时清掉这个空会话，避免列表里留僵尸 thread。
            clean_empty_threads()
            emit_empty_history_replay()
            emit_error(format_exc(exc, phase="start"), where="reset")
            return None
        state["thread_id"] = runner.thread.id
        state["project_path"] = project_path
        state.pop("pending_config", None)
        emit_history_replay(runner)
        emit_execution_state(runner)
        emit_execution_context(runner)
        log(
            "[wire] reset：已开新会话"
            + (f" backend={reset_config.backend}" if reset_config.backend else "")
        )
        return runner

    if cmd == "cancel":
        # Harness Spine: cancel is scoped to the active thread only.
        # Background threads are unaffected.
        # 验收 P0-4：携带 run_id 时必须匹配当前活动 Run——旧 Run 的迟到
        # Cancel 不得取消新 Run（不匹配 → 拒绝，不触碰 Runner）。
        active_tid = _active_thread_id(state)
        bound_run_id = command.get("run_id", "")
        if isinstance(bound_run_id, str) and bound_run_id:
            session = _harness_manager.get_session(active_tid)
            if session is None or session.active_run_id != bound_run_id:
                log(
                    f"[wire] cancel rejected: run_id {bound_run_id} != "
                    f"active {getattr(session, 'active_run_id', None)} for {active_tid}"
                )
                return runner
        if runner is not None and _turn_active_for_thread(state, active_tid):
            # M1: 控制面经 RunEngine（run_id 绑定校验在内）
            engine = _get_engine()
            engine.register_runner(active_tid, runner)
            engine.cancel_run(active_tid, bound_run_id or None)
            _cancel_thread_turn(state, active_tid)
            log(f"[wire] cancel：已请求停止 {active_tid}")
        else:
            log("[wire] cancel：当前没有运行中的任务")
        return runner

    # ── Harness Spine: input/send (single message_id, harness routing) ─
    if cmd == "input/send":
        text = command.get("text", "")
        thread_id = state.get("thread_id", "")
        if not isinstance(text, str) or not text.strip():
            reject_msg = InputMessage.create(thread_id or "default", text or "")
            _emit_input_state_ack(
                reject_msg.message_id,
                thread_id,
                "rejected",
                detail="Empty input",
            )
            return runner
        # Create ONE InputMessage and route through the harness manager.
        # The same message_id is carried through the entire lifecycle:
        #   accepted → queued/immediate_pending → applied/deferred/rejected
        delivery_str = command.get("delivery", "auto")
        try:
            delivery = (
                InputDelivery(delivery_str)
                if delivery_str in {"auto", "immediate", "enqueue"}
                else InputDelivery.AUTO
            )
        except ValueError:
            delivery = InputDelivery.AUTO
        # Session mode from the UI is carried into the Run's requested options
        mode_str = command.get("mode", "")
        requested_mode = None
        if isinstance(mode_str, str) and mode_str in {"ask", "plan", "run"}:
            from electromind.harness.state import SessionMode

            requested_mode = SessionMode(mode_str)
        # P3: 模型 policy 随 Run 携带（auto/fast/balanced/best/plan-execute/
        # 具体模型 id）—— 覆盖本线程 config，_build_run_snapshot 与
        # run_user_turn 的 resolved_model() 都按此解析（Run 开始后固定）。
        model_str = command.get("model", "")
        if isinstance(model_str, str) and model_str.strip():
            config = replace(config, model=model_str.strip())
        msg = InputMessage.create(
            thread_id or "default",
            text,
            delivery=delivery,
            requested_mode=requested_mode,
        )
        receipt = await _harness_manager.send_input(msg)
        # Gate 1, 二-5: IMMEDIATE/AUTO inputs during an active Run are
        # delivered to the Runner's inbound mailbox — the loop applies
        # them at its next SAFE CHECKPOINT (never mid-tool-batch).  The
        # message STAYS in pending_immediate (persisted) until the Run
        # settles it, so a crash between steer and checkpoint cannot lose
        # it; the Run end re-queues unread steers with their ORIGINAL
        # identity.
        if str(receipt.state) == "immediate_pending":
            # M1: 立即输入经 RunEngine 注入语义检查点（message_id 随行，
            # Run 结束 settle 按 id 精确分类，永不按文本猜）。
            engine = _get_engine()
            if runner is not None:
                engine.register_runner(receipt.thread_id, runner)
            engine.steer(receipt.thread_id, text, message_id=receipt.message_id)
            log(f"[wire] {receipt.thread_id} steer → checkpoint: {text[:40]}")
        _emit_input_state_ack(
            receipt.message_id,
            receipt.thread_id,
            str(receipt.state),
            detail=receipt.detail,
            target_run_id=receipt.target_run_id,
            request_id=command.get("request_id", ""),
        )
        # Gate 2: persist queue/immediate changes immediately
        _persist_thread_state(receipt.thread_id)
        # Capture ACK payload for idempotent replay
        command["_ack_payload"] = {
            "_ack_method": "input/state",
            "message_id": receipt.message_id,
            "thread_id": receipt.thread_id,
            "state": str(receipt.state),
            "detail": receipt.detail,
        }
        # Store for the "user" handler below so it reuses the same identity
        command["_input_msg"] = msg
        command["_input_receipt"] = receipt
        # Rewrite to "user" so existing runner logic applies below
        cmd = "user"

    # ── Harness Spine: thread/snapshot (runnerless) ────────────────────
    if cmd == "thread/snapshot":
        thread_id = command.get("thread_id") or state.get("thread_id", "")
        snap = await _harness_manager.get_snapshot(thread_id)
        # Protocol v2: durable timeline — completed messages, tool calls,
        # tool results and errors so the client can rebuild the full
        # thread even when the event buffer was evicted.
        if isinstance(thread_id, str) and thread_id:
            try:
                project_path = state.get("project_path")
                thread = open_thread_history(
                    thread_id,
                    project_path if isinstance(project_path, str) else None,
                )
                snap["items"] = history_message_items(thread.messages)
            except Exception as exc:
                log(f"[wire] snapshot items failed: {exc}")
                snap["items"] = []
        # Protocol v2: include buffered events for incremental recovery
        after_seq_raw = command.get("after_seq")
        if isinstance(after_seq_raw, (int, float)) and int(after_seq_raw) >= 0:
            after_seq = int(after_seq_raw)
            broker = _get_broker()
            snap["after_seq"] = after_seq
            snap["last_seq"] = broker.get_last_seq(thread_id or "")
            buffered = broker.get_events_since(thread_id or "", after_seq)
            if buffered:
                snap["events"] = [
                    {
                        "event_id": e.event_id,
                        "seq": e.seq,
                        "method": e.method,
                        "thread_id": e.thread_id,
                        "run_id": e.run_id,
                        "item_id": e.item_id,
                        "payload": e.payload,
                    }
                    for e in buffered
                ]
                snap["is_full_snapshot"] = False
            else:
                # Distinguish "no new events" from "history evicted"
                oldest_buffered_seq = (
                    broker._seq.get(thread_id or "", 0) - broker._max_buffer
                )
                history_intact = after_seq < 0 or after_seq >= oldest_buffered_seq
                snap["is_full_snapshot"] = not history_intact or after_seq < 0
        request_id = command.get("request_id", "")
        if isinstance(request_id, str) and request_id:
            snap["request_id"] = request_id
        # G1: 快照携带 Plan / Artifact 领域状态（Desktop 重启后完整恢复：
        # Thread / Run / Plan / Approval / Artifact 状态可重建）
        try:
            engine = _get_engine()
            plan = engine.plan_state(thread_id)
            snap["plan"] = plan.to_dict() if plan else None
            snap["artifacts"] = [m.to_dict() for m in engine.artifacts(thread_id)]
        except Exception as exc:  # 快照不因领域状态失败而整体失败
            log(f"[wire] snapshot plan/artifacts failed: {exc}")
        _emit_jsonrpc("thread/snapshot", snap)
        return runner

    # ── G1: Plan 领域状态命令 ─────────────────────────────────────────
    if cmd in {
        "plan/state",
        "plan/propose",
        "plan/approve",
        "plan/revise",
        "plan/cancel",
        "plan/update-step",
    }:
        thread_id = command.get("thread_id") or state.get("thread_id", "")
        engine = _get_engine()
        try:
            if cmd == "plan/state":
                plan = engine.plan_state(thread_id)
                _emit_jsonrpc(
                    "plan/state",
                    {"thread_id": thread_id, "plan": plan.to_dict() if plan else None},
                )
            elif cmd == "plan/propose":
                raw = command.get("plan")
                if not isinstance(raw, dict):
                    emit_error(
                        "plan/propose 需要 plan 字段（PlanState dict）", where=cmd
                    )
                else:
                    raw.setdefault("plan_id", "default")
                    from electromind.execution.plan import PlanState

                    engine.plan_propose(thread_id, PlanState.from_dict(raw))
            elif cmd == "plan/approve":
                engine.plan_approve(thread_id)
            elif cmd == "plan/revise":
                engine.plan_revise(thread_id)
            elif cmd == "plan/cancel":
                engine.plan_cancel(thread_id)
            elif cmd == "plan/update-step":
                from electromind.execution.plan import StepStatus

                step_id = str(command.get("step_id", ""))
                status = StepStatus(str(command.get("status", "")))
                if not step_id:
                    emit_error("plan/update-step 需要 step_id", where=cmd)
                else:
                    engine.plan_update_step(thread_id, step_id, status)
        except ValueError as exc:
            emit_error(str(exc), where=cmd)
        return runner

    # ── G1: Artifact 领域状态命令 ─────────────────────────────────────
    if cmd in {
        "artifact/state",
        "artifact/register",
        "artifact/accept",
        "artifact/reject",
        "artifact/complete",
        "artifact/validate",
    }:
        thread_id = command.get("thread_id") or state.get("thread_id", "")
        engine = _get_engine()
        try:
            if cmd == "artifact/state":
                _emit_jsonrpc(
                    "artifact/state",
                    {
                        "thread_id": thread_id,
                        "artifacts": [m.to_dict() for m in engine.artifacts(thread_id)],
                    },
                )
            elif cmd == "artifact/register":
                raw = command.get("manifest")
                if not isinstance(raw, dict):
                    emit_error("artifact/register 需要 manifest 字段", where=cmd)
                else:
                    from electromind.artifacts.manifest import ArtifactManifest

                    engine.artifact_register(thread_id, ArtifactManifest.from_dict(raw))
            elif cmd == "artifact/accept":
                artifact_id = str(command.get("artifact_id", ""))
                who = str(command.get("who", "user")) or "user"
                manifest = engine.artifact_accept(thread_id, artifact_id, who=who)
                if manifest is None:
                    emit_error(f"artifact 不存在: {artifact_id}", where=cmd)
            elif cmd == "artifact/reject":
                artifact_id = str(command.get("artifact_id", ""))
                reason = str(command.get("reason", ""))
                manifest = engine.artifact_reject(thread_id, artifact_id, reason=reason)
                if manifest is None:
                    emit_error(f"artifact 不存在: {artifact_id}", where=cmd)
            elif cmd == "artifact/complete":
                artifact_id = str(command.get("artifact_id", ""))
                manifest = engine.artifact_complete(thread_id, artifact_id)
                if manifest is None:
                    emit_error(f"artifact 不存在: {artifact_id}", where=cmd)
            elif cmd == "artifact/validate":
                artifact_id = str(command.get("artifact_id", ""))
                parser = str(command.get("parser", ""))
                # P2.4: 跑确定性 Parser，通过才 VALIDATED；否则 validation=REJECTED。
                manifest, parse_result = engine.artifact_validate_with_parser(
                    thread_id, artifact_id, parser=parser
                )
                if manifest is None:
                    emit_error(f"artifact 不存在: {artifact_id}", where=cmd)
                elif parse_result is not None and not parse_result.valid:
                    emit_error(
                        f"artifact {artifact_id} 解析未通过（{parse_result.outcome}）: "
                        f"{parse_result.summary}",
                        where=cmd,
                    )
        except ValueError as exc:
            emit_error(str(exc), where=cmd)
        return runner

    # ── P3: HPC 提交记录查询（Desktop Inspector 任务页）───────────────
    if cmd == "hpc/submissions":
        thread_id = command.get("thread_id") or state.get("thread_id", "")
        try:
            from electromind.hpc import SubmissionStore

            store = SubmissionStore()
            records = store.find_by_thread(thread_id) if thread_id else store.all()
            _emit_jsonrpc(
                "hpc/submissions",
                {
                    "thread_id": thread_id,
                    "submissions": [
                        r.to_dict() for r in sorted(records, key=lambda r: r.created_at)
                    ],
                },
            )
        except Exception as exc:  # noqa: BLE001 — 查询失败不算协议错误
            emit_error(f"hpc/submissions 查询失败: {exc}", where=cmd)
        return runner

    # ── Slash commands: intercepted BEFORE opening a runner ────────────
    # Known slash commands are read-only local capabilities; /help and
    # /sessions must work even without an open runner (no sandbox wake).
    if cmd == "user":
        text = command.get("text", "")
        if isinstance(text, str) and text.lstrip().startswith("/"):
            slash_name = text.strip().lstrip("/").split()[0]
            known_commands = {item["name"] for item in SLASH_COMMANDS}
            if slash_name in known_commands:
                try:
                    await run_slash_command(slash_name, runner)
                except Exception as exc:
                    log(f"[wire] slash failed: {exc}")
                    emit_error(format_exc(exc), where="slash")
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
        emit_execution_state(runner)
        emit_execution_context(runner)
        emit_history_replay(runner)

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
        thread_id = state.get("thread_id", runner.thread.id if runner else "")
        tid = thread_id or "default"
        # If input already went through the harness (from input/send),
        # reuse the same message_id — don't create a second identity.
        input_msg: InputMessage | None = command.get("_input_msg")
        input_receipt = command.get("_input_receipt")
        if input_msg is not None and input_receipt is not None:
            # Already routed by input/send.  Only start a turn if this
            # thread is idle (the harness queued it) — otherwise the
            # input is already enqueued for the active run.
            if _turn_active_for_thread(state, tid):
                log(f"[wire] input already enqueued for active run on {tid}")
                return runner
        elif _turn_active_for_thread(state, tid):
            # Legacy "user" command with no prior harness routing.
            # Enqueue instead of silently dropping.
            msg = InputMessage.create(
                tid,
                text,
                delivery=InputDelivery.ENQUEUE,
            )
            receipt = await _harness_manager.send_input(msg)
            _emit_input_state_ack(
                receipt.message_id,
                receipt.thread_id,
                str(receipt.state),
                detail=receipt.detail,
            )
            log(f"[wire] turn active, enqueued: {text[:50]}")
            return runner
        # 落一次 metainfo：首条用户消息定标题，供前端会话列表展示面向用户的名字。
        touch_thread_metainfo(runner, text)
        # Harness Spine: workspace write lease BEFORE the Run starts.
        # Conflict → the input stays queued and the Run waits (the auto-
        # start chain retries once the holder releases).  Read-only modes
        # (ask/plan) never acquire the lease.
        from electromind.harness.identity import new_run_id
        from electromind.harness.state import SessionMode

        ws_key = _workspace_key_for(runner)
        # The UI's per-input requested mode drives BOTH the lease decision
        # and the frozen RunSnapshot — a "plan" input must never acquire a
        # write lease or run with write capability (Gate 1, 八 / 一-7).
        requested_mode = getattr(command.get("_input_msg"), "requested_mode", None)
        session_mode = _resolved_session_mode(config, requested_mode)
        pre_run_id = new_run_id()
        if ws_key is not None:
            acquired = await _harness_manager.try_acquire_workspace(
                tid, ws_key, pre_run_id, session_mode
            )
            if not acquired:
                # Register as a waiter: the holder's release wakes us
                # (Gate 1, 八 — a conflict must not wait forever).  The
                # runner is registered first so the wake-up can start the
                # Run even though start_run never ran (session.runner
                # would be None).
                _save_runner(state, tid, runner)
                _harness_manager.register_workspace_waiter(tid, ws_key)
                _emit_input_state_ack(
                    getattr(command.get("_input_msg"), "message_id", "") or "",
                    tid,
                    "queued",
                    detail=f"waiting_for_workspace:{ws_key}",
                )
                log(f"[wire] {tid} waiting for workspace {ws_key}")
                return runner  # Input stays queued for the next attempt
        # Harness Spine: atomically consume the queued input and create
        # the Run (single entry — no separate preparation stage).
        start_result = await _harness_manager.start_run(tid, runner, run_id=pre_run_id)
        if start_result is None:
            # Run did not start — release the pre-acquired lease if any
            await _harness_manager.release_workspace(tid, pre_run_id)
            log(f"[wire] start_run failed for {tid}")
            return runner
        run_id, consumed_msg = start_result
        # Gate 1, 一-7: freeze the immutable RunSnapshot at Run creation.
        await _harness_manager.set_run_snapshot(
            tid,
            _build_run_snapshot(
                runner,
                config,
                run_id,
                tid,
                getattr(consumed_msg, "message_id", ""),
                requested_mode=getattr(consumed_msg, "requested_mode", None),
            ),
        )
        # Gate 2: persist the active-run marker BEFORE the turn starts so a
        # crash mid-Run can be marked interrupted (never completed).
        _persist_thread_state(tid)
        # Use the consumed message's text and identity for the turn.
        # The message_id from send_input is now the canonical identity.
        turn_text = getattr(consumed_msg, "text", text)
        requested_mode = getattr(consumed_msg, "requested_mode", None)
        turn_msg_id = getattr(consumed_msg, "message_id", "")
        task = asyncio.create_task(
            run_user_turn(
                runner,
                turn_text,
                config,
                state,
                requested_mode=requested_mode,
            )
        )
        _set_turn(state, tid, task)
        # Emit the final "applied" ACK with the consumed message's identity
        if turn_msg_id:
            _emit_input_state_ack(
                turn_msg_id,
                tid,
                "applied",
                detail="Turn started",
            )
        return runner

    if cmd == "permit":
        tool_call_id = command.get("tool_call_id")
        if not (isinstance(tool_call_id, str) and tool_call_id):
            log("[wire] permit missing tool_call_id")
            return runner
        # Harness Spine: validate approval scope before resolving.
        approval_id = command.get("approval_id", "")
        thread_id = command.get("thread_id", "")
        run_id = command.get("run_id", "")
        scope_ok, resolved_approval = await _approval_scope_valid(
            runner, tool_call_id, approval_id, thread_id, run_id, approved=True
        )
        if not scope_ok:
            log(f"[wire] permit rejected: scope mismatch for {tool_call_id}")
            _emit_jsonrpc(
                "approval/resolved",
                {
                    "thread_id": thread_id or "",
                    "run_id": run_id or "",
                    "approval_id": approval_id or "",
                    "tool_call_id": tool_call_id,
                    "status": "expired",
                },
            )
            return runner
        engine = _get_engine()
        if thread_id and runner is not None:
            engine.register_runner(thread_id, runner)
        engine.permit_tool(thread_id or "", run_id or "", tool_call_id)
        # P0-4: 记录审批时的参数摘要，执行时校验参数未被篡改
        if runner is not None and resolved_approval is not None:
            rec = getattr(runner, "record_approved_arguments", None)
            if callable(rec):
                rec(tool_call_id, getattr(resolved_approval, "arguments_digest", ""))
        _emit_jsonrpc(
            "approval/resolved",
            {
                "thread_id": thread_id or "",
                "run_id": run_id or "",
                "approval_id": approval_id or "",
                "tool_call_id": tool_call_id,
                "status": "approved",
            },
        )
        return runner

    if cmd == "deny":
        tool_call_id = command.get("tool_call_id")
        if not (isinstance(tool_call_id, str) and tool_call_id):
            log("[wire] deny missing tool_call_id")
            return runner
        reason = command.get("reason", "")
        # Harness Spine: validate approval scope before resolving.
        approval_id = command.get("approval_id", "")
        thread_id = command.get("thread_id", "")
        run_id = command.get("run_id", "")
        scope_ok, _resolved = await _approval_scope_valid(
            runner, tool_call_id, approval_id, thread_id, run_id, approved=False
        )
        if not scope_ok:
            log(f"[wire] deny rejected: scope mismatch for {tool_call_id}")
            _emit_jsonrpc(
                "approval/resolved",
                {
                    "thread_id": thread_id or "",
                    "run_id": run_id or "",
                    "approval_id": approval_id or "",
                    "tool_call_id": tool_call_id,
                    "status": "expired",
                },
            )
            return runner
        engine = _get_engine()
        if thread_id and runner is not None:
            engine.register_runner(thread_id, runner)
        engine.deny_tool(
            thread_id or "",
            run_id or "",
            tool_call_id,
            reason=reason if isinstance(reason, str) else "",
        )
        _emit_jsonrpc(
            "approval/resolved",
            {
                "thread_id": thread_id or "",
                "run_id": run_id or "",
                "approval_id": approval_id or "",
                "tool_call_id": tool_call_id,
                "status": "denied",
            },
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
    state: dict = {
        "turn": None,
        "client_features": {},
        "_runners": {},  # Harness Spine: per-thread runner registry
        "_turns": {},  # Harness Spine: per-thread turn task registry
    }
    had_user_turn = False
    # 启动即下发 slash 命令清单，前端无需显式请求就能填充斜杠菜单。
    emit_slash_commands()
    if config.thread_id:
        runner = await open_thread_runner(config, config.thread_id)
        state["thread_id"] = runner.thread.id
        emit_history_replay(runner)
    # Gate 2 recovery: mark interrupted runs, restore queued inputs and
    # expire unverifiable approvals from a previous process lifetime.
    await _recover_thread_states()
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
        # Cancel all per-thread turns
        turns: dict = state.get("_turns", {})
        for tid, task in list(turns.items()):
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        # Also handle legacy turn
        task = state.get("turn")
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        # Close active runner
        if runner is not None:
            thread_id = runner.thread.id
            await runner.close()
            clean_empty_threads(keep_thread_ids={thread_id} if had_user_turn else set())
        # Close all background runners
        runners: dict = state.get("_runners", {})
        for tid, bg_runner in runners.items():
            try:
                await bg_runner.close()
            except Exception:
                pass
    return 0

"""EmbeddedAgentClient — 进程内 Harness 客户端（CLI-4）。

CLI 不再以单个 Runner 为全局状态事实源；所有输入、事件、审批、取消都通过本
客户端进入 Harness 生命周期（ThreadSessionManager + EventBroker + IdempotencyStore）：

- 每 Thread 一个 Runner 缓存：切换视图/恢复会话不关闭 Runner，后台 Run 继续
- 所有事件经 EventBroker 打 thread_id / seq / event_id，Run 事件带 run_id，
  Item 事件带 item_id（与 wire / Desktop 同一协议形状）
- Approval / Cancel 精确绑定 thread_id + run_id（Manager 校验后原子消费）
- 相同 request_id 重试只回放原结果，不重复执行副作用
- IMMEDIATE 输入在 Run 内检查点 steer（applied）；ENQUEUE 严格 FIFO 在下一 Run
- Run 启动时冻结 RunSnapshot（mode/model/max_iterations/target/policy/tools 摘要）

事件形状（JSON-RPC notification，与 wire ``_emit_jsonrpc`` 一致）：
``{"jsonrpc":"2.0","method":<name>,"params":{...envelope...}}``。
"""

from __future__ import annotations

import asyncio

from electromind.harness.identity import (
    RunSnapshot,
    WorkspaceKey,
    new_approval_id,
    new_run_id,
)
from electromind.harness.inbound import (
    InputDelivery,
    InputMessage,
    InputReceipt,
)
from electromind.harness.protocol_v2 import EventBroker, EventEnvelope, IdempotencyStore
from electromind.harness.session_manager import ThreadSessionManager
from electromind.harness.state import (
    ExecutionTargetSnapshot,
    InputDeliveryState,
    PermissionPolicySnapshot,
    SessionMode,
)

from .tool_permit import requires_permit_prompt, risk_hint, summarize_tool_args

_MODE_TO_SESSION = {
    "ask": SessionMode.ASK,
    "plan": SessionMode.PLAN,
    "run": SessionMode.RUN,
}


class EmbeddedAgentClient:
    """进程内 Harness 客户端。``event_sink`` 是唯一出口（transport 无关）。"""

    def __init__(
        self,
        runner_factory,
        *,
        config=None,
        event_sink=None,
        idle_ttl_seconds: float = 900.0,
        persist_meta: bool = True,
    ) -> None:
        self._runner_factory = runner_factory  # async (thread_id) -> Runner
        self._config = config
        self._event_sink = event_sink  # callable(dict event line) or None
        self.persist_meta = persist_meta  # --no-session-persistence 时关闭
        self.manager = ThreadSessionManager(_idle_ttl_seconds=idle_ttl_seconds)
        self.broker = EventBroker()
        self.idempotency = IdempotencyStore()
        # M1: 唯一 Run 生命周期（与 manager 同源）
        from electromind.engine import RunEngine

        self.engine = RunEngine(manager=self.manager)
        self._runners: dict[str, object] = {}
        self._run_tasks: dict[str, asyncio.Task] = {}
        self._run_workspace: dict[str, WorkspaceKey] = {}  # run_id → 写租约键
        self._message_request: dict[
            str, str
        ] = {}  # message_id → request_id（状态链路关联）
        self._closed = False

    # ------------------------------------------------------------------
    # 事件出口
    # ------------------------------------------------------------------

    def _emit(
        self,
        thread_id: str,
        method: str,
        params: dict,
        *,
        run_id: str | None = None,
        item_id: str | None = None,
    ) -> None:
        envelope = EventEnvelope.create(
            thread_id, method, params, run_id=run_id, item_id=item_id
        )
        tracked = self.broker.emit(envelope)
        params["seq"] = tracked.seq
        params["event_id"] = tracked.event_id
        params["protocol_version"] = tracked.protocol_version
        params["timestamp"] = tracked.timestamp
        line = {"jsonrpc": "2.0", "method": method, "params": params}
        if self._event_sink is not None:
            self._event_sink(line)

    # ------------------------------------------------------------------
    # 输入
    # ------------------------------------------------------------------

    async def send_input(
        self,
        thread_id: str,
        text: str,
        *,
        delivery: str = "auto",
        mode: str | None = None,
        request_id: str | None = None,
    ) -> InputReceipt:
        """接受输入并路由；幂等（同 request_id 重放原结果）。

        delivery: auto（空闲→新 Run）/ immediate（Run 内 steer）/ enqueue（FIFO）。
        """
        if request_id:
            if self.idempotency.is_duplicate(request_id):
                stored = self.idempotency.get_result(request_id)
                if stored is not None:
                    self._emit_input_state(thread_id, stored, request_id=request_id)
                    return stored

        requested_mode = None
        if mode in _MODE_TO_SESSION:
            requested_mode = _MODE_TO_SESSION[mode]
        message = InputMessage.create(
            thread_id,
            text,
            delivery=InputDelivery(delivery),
            requested_mode=requested_mode,
        )
        receipt = await self.manager.send_input(message)
        if request_id:
            self.idempotency.record(request_id, receipt)
            self._message_request[receipt.message_id] = request_id
            if str(receipt.state) == "rejected":
                # 四轮复验 P0：rejected 是终态，立即清理关联
                self._message_request.pop(receipt.message_id, None)
        self._emit_input_state(thread_id, receipt, request_id=request_id)

        # delivery=auto 且 thread 空闲 → 自动启动 Run
        if receipt.state == InputDeliveryState.QUEUED and not self.has_active_run(
            thread_id
        ):
            await self.start_run(thread_id)
        return receipt

    def _emit_input_state(
        self, thread_id: str, receipt: InputReceipt, request_id: str = ""
    ) -> None:
        """input/state 事件；request_id 原样回显，供 TUI 关联乐观渲染的输入。"""
        params = {
            "thread_id": thread_id,
            "message_id": receipt.message_id,
            "state": str(receipt.state),
            "detail": receipt.detail or "",
            "target_run_id": receipt.target_run_id or "",
        }
        if request_id:
            params["request_id"] = request_id
        self._emit(thread_id, "input/state", params)

    # ------------------------------------------------------------------
    # Run 生命周期
    # ------------------------------------------------------------------

    async def _get_or_create_runner(self, thread_id: str):
        if thread_id not in self._runners:
            self._runners[thread_id] = await self._runner_factory(thread_id)
        return self._runners[thread_id]

    def runner(self, thread_id: str, *, create: bool = False):
        """当前 thread 的 Runner（不创建除非 create=True）。"""
        if thread_id in self._runners:
            return self._runners[thread_id]
        return None

    def has_active_run(self, thread_id: str) -> bool:
        return self.manager.has_active_run(thread_id)

    async def get_runner(self, thread_id: str):
        """公开的 Runner 获取/创建（slash 命令与 ! 命令需要）。"""
        return await self._get_or_create_runner(thread_id)

    async def start_run(self, thread_id: str) -> bool:
        """消费队头输入并启动 Run；返回是否启动。"""
        session = self.manager.get_session(thread_id)
        peek = self.manager.peek_queued_input(thread_id)
        if session is None or peek is None:
            return False
        if self.manager.has_active_run(thread_id):
            return False
        run_id = new_run_id()
        runner = await self._get_or_create_runner(thread_id)
        mode = self._input_mode(peek)
        key: WorkspaceKey | None = None
        if mode in (SessionMode.ASK, SessionMode.PLAN):
            pass  # 只读 Run 不抢写租约
        else:
            key = self._workspace_key(runner, thread_id)
            if key is not None and not await self.manager.try_acquire_workspace(
                thread_id, key, run_id, mode
            ):
                # 写租约被其他 Thread 持有：注册等待，输入保持排队
                self.manager.register_workspace_waiter(thread_id, key)
                return False

        started = await self.manager.start_run(thread_id, runner, run_id=run_id)
        if started is None:
            if mode not in (SessionMode.ASK, SessionMode.PLAN):
                await self.manager.release_workspace(thread_id, run_id)
            return False
        run_id, input_message = started
        if mode not in (SessionMode.ASK, SessionMode.PLAN) and key is not None:
            self._run_workspace[run_id] = key
        # 四轮复验 P0：普通 queued 输入的 applied 终态——输入被 Run 消费即
        # 发送带原 request_id 的 applied，并清理关联映射（终态）。
        self._emit_consumed_applied(thread_id, input_message)
        task = asyncio.create_task(self._run_loop(thread_id, run_id, input_message))
        self._run_tasks[thread_id] = task
        return True

    def _emit_consumed_applied(
        self, thread_id: str, input_message: InputMessage
    ) -> None:
        """Run 消费队头输入 → input/state(applied, 原 request_id) + 清理映射。"""
        request_id = self._message_request.get(input_message.message_id, "")
        params = {
            "thread_id": thread_id,
            "message_id": input_message.message_id,
            "state": str(InputDeliveryState.APPLIED),
            "detail": "consumed by run",
        }
        if request_id:
            params["request_id"] = request_id
        self._emit(thread_id, "input/state", params)
        self._message_request.pop(input_message.message_id, None)

    def _input_mode(self, message: InputMessage) -> SessionMode:
        if message.requested_mode is not None:
            return message.requested_mode
        config = self._config
        if config is not None and getattr(config, "session_mode", None):
            return _MODE_TO_SESSION.get(config.session_mode, SessionMode.RUN)
        return SessionMode.RUN

    def _workspace_key(self, runner, thread_id: str) -> WorkspaceKey | None:
        """Run 的执行目标 → 写租约键。解析失败返回 None（不阻塞）。"""
        try:
            target = self._execution_target(runner, thread_id)
            key = target.workspace_key()
            return WorkspaceKey(
                execution_target_id=key.split(":")[0] if ":" in key else key,
                canonical_workdir=target.workdir,
            )
        except Exception:
            return None

    def _execution_target(self, runner, thread_id: str) -> ExecutionTargetSnapshot:
        execution = getattr(runner, "_execution", None)
        if execution is not None:
            kind = getattr(execution, "mode", "local") or "local"
            profile = getattr(execution, "resolved_backend", "") or kind
        else:
            kind = "local"
            profile = "local"
        sandbox = getattr(runner, "sandbox", None)
        workdir = getattr(sandbox, "workdir", "") or ""
        if not workdir:
            project = getattr(getattr(runner, "thread", None), "project_path", "")
            workdir = str(project) if project else ""
        return ExecutionTargetSnapshot(
            target_id=profile, kind=kind, workdir=workdir, profile_id=profile
        )

    # ------------------------------------------------------------------
    # Run 事件循环
    # ------------------------------------------------------------------

    async def _run_loop(
        self, thread_id: str, run_id: str, input_message: InputMessage
    ) -> None:
        from electromind import (
            ReasoningDelta,
            RunEnd,
            TextDelta,
            ToolCallBegin,
            ToolResult,
        )

        runner = self._runners[thread_id]
        snapshot = self._build_run_snapshot(runner, thread_id, run_id, input_message)
        await self.manager.set_run_snapshot(thread_id, snapshot)
        self._emit(
            thread_id,
            "run/started",
            {
                "thread_id": thread_id,
                "run_id": run_id,
                "session_mode": str(snapshot.session_mode),
                "model": snapshot.model,
                "max_iterations": snapshot.max_iterations,
            },
            run_id=run_id,
        )

        success = False
        cancelled = False
        stop_reason = ""

        async def _emit_event(thread_id_, run_id_, event, seq) -> None:
            nonlocal stop_reason
            # IMMEDIATE 输入在检查点 steer（applied）
            await self._drain_immediate(thread_id_, runner)
            if isinstance(event, RunEnd):
                stop_reason = event.stop_reason
            if isinstance(event, TextDelta):
                self._emit(
                    thread_id_,
                    "item/delta",
                    {
                        "thread_id": thread_id_,
                        "run_id": run_id_,
                        "item_id": f"item-{run_id_}-text",
                        "kind": "text",
                        "text": event.text,
                    },
                    run_id=run_id_,
                    item_id=f"item-{run_id_}-text",
                )
            elif isinstance(event, ReasoningDelta):
                self._emit(
                    thread_id_,
                    "item/delta",
                    {
                        "thread_id": thread_id_,
                        "run_id": run_id_,
                        "item_id": f"item-{run_id_}-reasoning",
                        "kind": "reasoning",
                        "text": event.text,
                    },
                    run_id=run_id_,
                    item_id=f"item-{run_id_}-reasoning",
                )
            elif isinstance(event, ToolCallBegin):
                item_id = f"item-{event.tool_call_id}"
                self._emit(
                    thread_id_,
                    "item/started",
                    {
                        "thread_id": thread_id_,
                        "run_id": run_id_,
                        "item_id": item_id,
                        "kind": "tool",
                        "tool_call_id": event.tool_call_id,
                        "name": event.name,
                        "arguments": event.arguments,
                    },
                    run_id=run_id_,
                    item_id=item_id,
                )
            elif isinstance(event, ToolResult):
                item_id = f"item-{event.tool_call_id}"
                self._emit(
                    thread_id_,
                    "item/completed",
                    {
                        "thread_id": thread_id_,
                        "run_id": run_id_,
                        "item_id": item_id,
                        "kind": "tool",
                        "tool_call_id": event.tool_call_id,
                        "ok": bool(event.ok),
                        "content": event.content or "",
                    },
                    run_id=run_id_,
                    item_id=item_id,
                )

        async def _on_approval(thread_id_, run_id_, event) -> None:
            await self._request_approval(thread_id_, run_id_, runner, event)

        async def _before_finish(thread_id_, run_id_, outcome) -> None:
            # 终态转换前：未应用的 immediate 输入取走并原位放回队首
            # （转换会 defer 剩余项），逐条发 deferred（带原 request_id）。
            session = self.manager.get_session(thread_id_)
            if session is None or session.active_run_id != run_id_:
                return
            deferred = await self.manager.take_pending_immediate(thread_id_)
            if not deferred:
                return
            self.manager.restore_queued_at_head(thread_id_, deferred)
            for message in deferred:
                params = {
                    "thread_id": thread_id_,
                    "message_id": message.message_id,
                    "state": str(InputDeliveryState.DEFERRED),
                    "detail": "Run ended before the message could be applied",
                }
                request_id = self._message_request.pop(message.message_id, "")
                if request_id:
                    params["request_id"] = request_id
                self._emit(thread_id_, "input/state", params)

        async def _on_finish(thread_id_, run_id_, outcome) -> None:
            nonlocal success, cancelled
            success = outcome == "completed"
            cancelled = outcome == "cancelled"
            await self._finish_run(
                thread_id_,
                run_id_,
                success=success,
                cancelled=cancelled,
                stop_reason=stop_reason,
            )

        try:
            outcome = await self.engine.run_loop(
                thread_id,
                runner,
                input_message.text,
                emitter=_emit_event,
                needs_permit=lambda ev: self._needs_approval(thread_id, ev),
                on_approval=_on_approval,
                before_finish=_before_finish,
                on_finish=_on_finish,
            )
            success = outcome == "completed"
            cancelled = outcome == "cancelled"
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            stop_reason = "error"
        # 注意：异常路径的终态（run/completed failed）由 RunEngine 的
        # try/finally 统一发出（on_finish 回调），此处不再重复。

        if self.persist_meta:
            status = (
                "cancelled" if cancelled else ("failed" if not success else "completed")
            )
            _update_metainfo(runner, input_message.text, status=status)

    def _needs_approval(self, thread_id: str, event) -> bool:
        from .tool_permit import runner_supports_permit

        runner = self._runners.get(thread_id)
        if runner is None or not runner_supports_permit(runner):
            return False
        mode = self._config.resolved_permission_mode() if self._config else "prompt"
        return requires_permit_prompt(mode, event)

    async def _drain_immediate(self, thread_id: str, runner) -> None:
        messages = await self.manager.take_pending_immediate(thread_id)
        for message in messages:
            # M1: 立即输入经 RunEngine 注入语义检查点（message_id 随行）
            self.engine.steer(thread_id, message.text, message_id=message.message_id)
            params = {
                "thread_id": thread_id,
                "message_id": message.message_id,
                "state": str(InputDeliveryState.APPLIED),
                "detail": "steered at checkpoint",
            }
            request_id = self._message_request.pop(message.message_id, "")
            if request_id:
                params["request_id"] = request_id  # 同一输入链路持续携带
            self._emit(thread_id, "input/state", params)

    async def _request_approval(
        self, thread_id: str, run_id: str, runner, event
    ) -> bool:
        from electromind.harness.workspace import ApprovalRequest

        sandbox = getattr(runner, "sandbox", None)
        workdir = getattr(sandbox, "workdir", "") or ""
        command = summarize_tool_args(event.name, event.arguments)
        approval = ApprovalRequest(
            approval_id=new_approval_id(),
            thread_id=thread_id,
            run_id=run_id,
            tool_call_id=event.tool_call_id,
            action_id=f"action:{event.tool_call_id}",
            target=self._execution_target(runner, thread_id).kind,
            workdir=workdir,
            risk=risk_hint(command),
            summary=command,
        )
        registered = await self.manager.add_approval(thread_id, approval)
        if registered:
            self._emit(
                thread_id,
                "approval/requested",
                {
                    "thread_id": thread_id,
                    "run_id": run_id,
                    "approval_id": approval.approval_id,
                    "tool_call_id": event.tool_call_id,
                    "action_id": approval.action_id,
                    "name": event.name,
                    "summary": command,
                    "target": approval.target,
                    "workdir": workdir,
                    "risk": approval.risk,
                },
                run_id=run_id,
            )
        return registered

    async def resolve_approval(
        self,
        thread_id: str,
        run_id: str,
        approval_id: str,
        approved: bool,
        tool_call_id: str | None = None,
    ) -> bool:
        """解析审批；校验 thread/run/status/tool_call 四元组后原子消费。"""
        runner = self._runners.get(thread_id)
        resolved = await self.manager.resolve_approval(
            thread_id, run_id, approval_id, approved, tool_call_id=tool_call_id
        )
        if resolved is None:
            return False
        if runner is not None and tool_call_id:
            if approved:
                self.engine.permit_tool(thread_id, run_id, tool_call_id)
            else:
                self.engine.deny_tool(
                    thread_id, run_id, tool_call_id, reason="user denied"
                )
        status = str(getattr(resolved, "status", ""))
        self._emit(
            thread_id,
            "approval/resolved",
            {
                "thread_id": thread_id,
                "run_id": run_id,
                "approval_id": approval_id,
                "tool_call_id": tool_call_id or "",
                "approved": approved,
                "status": status,
            },
            run_id=run_id,
        )
        return True

    async def cancel_run(self, thread_id: str, run_id: str | None = None) -> bool:
        """取消指定 Run（精确绑定，不碰其他 Thread）。

        复验 P0-4：Cancel 必须携带 run_id 且匹配该 Thread 当前活动 Run，
        否则拒绝——旧 Run 的迟到 Cancel 不得取消新 Run，也不允许无绑定取消。
        """
        if not run_id:
            return False  # 无 run_id 的 Cancel 一律拒绝（显式绑定是契约）
        # M1: 经 RunEngine（run_id 绑定校验在内）
        return self.engine.cancel_run(thread_id, run_id)

    # ------------------------------------------------------------------
    # 终态
    # ------------------------------------------------------------------

    async def _finish_run(
        self,
        thread_id: str,
        run_id: str,
        *,
        success: bool,
        cancelled: bool,
        stop_reason: str,
    ) -> None:
        session = self.manager.get_session(thread_id)
        released_key: WorkspaceKey | None = None
        if session is not None and session.active_run_id == run_id:
            # M1: 终态转换 / workspace 释放 / deferred 处理由 RunEngine
            # 统一完成（before_finish + _finish_run）；这里只负责事件与链。
            released_key = self._run_workspace.pop(run_id, None)

        # 释放写租约后唤醒等待者（Gate 1：不得让排队写入永远等待）
        if released_key is not None:
            for waiter in self.manager.take_workspace_waiters(released_key):
                if waiter != thread_id and not self.manager.has_active_run(waiter):
                    await self.start_run(waiter)

        self._emit(
            thread_id,
            "run/completed",
            {
                "thread_id": thread_id,
                "run_id": run_id,
                "stop_reason": stop_reason
                or ("cancelled" if cancelled else "completed"),
                "success": success,
                "usage": {},
            },
            run_id=run_id,
        )

        # 过期审批：Run 终结即失效（approval/resolved expired）
        expired = await self.manager.take_expired_approvals(thread_id)
        for approval in expired:
            self._emit(
                thread_id,
                "approval/resolved",
                {
                    "thread_id": thread_id,
                    "run_id": run_id,
                    "approval_id": getattr(approval, "approval_id", ""),
                    "tool_call_id": getattr(approval, "tool_call_id", ""),
                    "approved": False,
                    "status": "expired",
                },
                run_id=run_id,
            )

        # FIFO：成功后自动启动下一排队输入（失败不自动启动）
        self._run_tasks.pop(thread_id, None)
        if success:
            await self.start_run(thread_id)

    # ------------------------------------------------------------------
    # RunSnapshot 冻结
    # ------------------------------------------------------------------

    def _build_run_snapshot(
        self, runner, thread_id: str, run_id: str, input_message
    ) -> RunSnapshot:
        import hashlib
        from datetime import datetime

        spec = getattr(getattr(runner, "thread", None), "spec", None)
        mode = input_message.requested_mode or self._input_mode(input_message)
        model = self._config.resolved_model() if self._config else ""
        if spec is not None:
            model = getattr(spec, "model", None) or model
        max_iterations = self._config.resolved_max_turns() if self._config else 24
        project = getattr(getattr(runner, "thread", None), "project_path", "") or ""

        def _digest(text: str) -> str:
            return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16] if text else ""

        system_prompt = ""
        tools = []
        agent = getattr(runner, "agent", None)
        if agent is not None:
            system_prompt = str(getattr(agent, "system", "") or "")
            tools = getattr(agent, "tools", None) or []
        tool_digest = _digest(
            "\n".join(
                sorted(
                    str(getattr(t, "name", "")) for t in tools if getattr(t, "name", "")
                )
            )
        )
        target = self._execution_target(runner, thread_id)
        auto_approve = bool(self._config and self._config.permission_auto())
        return RunSnapshot(
            run_id=run_id,
            thread_id=thread_id,
            input_message_id=input_message.message_id,
            session_mode=mode,
            model=model,
            max_iterations=max_iterations,
            execution_target=target,
            permission_policy=PermissionPolicySnapshot(
                auto_approve=auto_approve,
                allow_file_write=mode == SessionMode.RUN,
                allow_execute=mode == SessionMode.RUN,
            ),
            project_path=project,
            system_prompt_digest=_digest(system_prompt),
            skill_set_digest="",
            tool_set_digest=tool_digest,
            created_at=datetime.now().isoformat(),
        )

    # ------------------------------------------------------------------
    # 快照 / 恢复 / 关闭
    # ------------------------------------------------------------------

    async def events(self, thread_id: str, after_seq: int = 0) -> list[EventEnvelope]:
        """断线重连恢复：after_seq 之后的事件（缓冲被淘汰时返回 []，走全量快照）。"""
        return self.broker.get_events_since(thread_id, after_seq)

    async def snapshot(self, thread_id: str) -> dict:
        """当前 thread 全量状态（含 run_snapshot 与排队输入）。"""
        return await self.manager.get_snapshot(thread_id)

    async def close_thread_runner(self, thread_id: str) -> bool:
        """关闭空闲 Runner（TTL 由管理方调用）。"""
        closed = await self.manager.close_idle_runner(thread_id)
        if closed and thread_id in self._runners:
            try:
                await self._runners[thread_id].close()
            except Exception:
                pass
            self._runners.pop(thread_id, None)
        return closed

    async def close(self) -> None:
        """关闭所有 Runner 并取消未完成 Run（进程退出路径）。"""
        if self._closed:
            return
        self._closed = True
        for task in list(self._run_tasks.values()):
            if not task.done():
                task.cancel()
        await asyncio.gather(*self._run_tasks.values(), return_exceptions=True)
        self._run_tasks.clear()
        for runner in list(self._runners.values()):
            try:
                await runner.close()
            except Exception:
                pass
        self._runners.clear()

    @property
    def thread_ids(self) -> list[str]:
        return self.manager.thread_ids


def _update_metainfo(runner, prompt: str, *, status: str = "completed") -> None:
    """会话 metainfo（title / updated_at / message_count / last_run_status），best-effort。"""
    try:
        from datetime import datetime as _dt

        meta = runner.thread.load_metainfo()
        now = _dt.now().isoformat(timespec="seconds")
        meta.setdefault("created_at", now)
        if not meta.get("title"):
            meta["title"] = prompt[:40] + ("…" if len(prompt) > 40 else "")
        meta["updated_at"] = now
        meta["message_count"] = len(runner.messages.data)
        meta["last_run_status"] = status  # 会话表“运行状态”列数据源
        runner.thread.save_metainfo(meta)
    except Exception:
        pass  # metainfo is best-effort

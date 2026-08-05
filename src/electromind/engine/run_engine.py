"""RunEngine — 唯一 Run 生命周期实现（M1）。

CLI / Wire / HTTP / Desktop 只与本类交互：

- **状态**：``ThreadSessionManager`` 是唯一状态权威；RunEngine 只通过
  manager 方法推进相位（含 RUNNING_MODEL / RUNNING_TOOL /
  WAITING_APPROVAL 精细相位），集中转换表唯一。
- **控制面**：cancel / steer / permit / deny 经 RunEngine 方法，App 层
  不再直接操作 ``runner.inbound`` / ``runner.checkpoint``。
- **事件**：通过 ``emitter`` 回调输出（wire 编码 / broker 编码），
  ``event_seq`` 由 manager 的 per-thread 计数器统一分配。
- **语义检查点**：取消 / 立即输入 / 审批在 runner 的六个命名检查点
  统一处理；ToolCall 永不孤立。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from ..core.events import RunEnd, ToolCallBegin, TurnResult
from ..harness import InputMessage, InputReceipt, ThreadSessionManager
from ..harness.state import RunPhase

# emitter 签名：emit(thread_id, run_id, event, seq) -> None | Awaitable[None]
Emitter = Callable[[str, str | None, object, int], "None | Awaitable[None]"]
# 审批请求回调：on_approval(thread_id, run_id, event) -> Awaitable
ApprovalHook = Callable[[str, str, ToolCallBegin], Awaitable[None]]
# 结束后回调：on_finish(thread_id, run_id, outcome) -> Awaitable
FinishHook = Callable[[str, str, str], Awaitable[None]]


class RunEngineError(RuntimeError):
    """Run 生命周期非法操作（run_id 不匹配 / 无活动 Run 等）。"""


@dataclass(slots=True)
class RunEngine:
    """唯一 Run 生命周期实现。

    ``manager`` 与 wire/http 共享（进程级单例）；``runners`` / ``tasks``
    是引擎维护的运行注册表。App 层通过本类的公开方法驱动一切。
    """

    manager: ThreadSessionManager = field(default_factory=ThreadSessionManager)
    _runners: dict[str, object] = field(default_factory=dict)
    _tasks: dict[str, asyncio.Task] = field(default_factory=dict)

    # ── Runner 注册 ──────────────────────────────────────────────────

    def register_runner(self, thread_id: str, runner: object) -> None:
        self._runners[thread_id] = runner

    def runner_for(self, thread_id: str) -> object | None:
        return self._runners.get(thread_id)

    def unregister_runner(self, thread_id: str) -> None:
        self._runners.pop(thread_id, None)

    # ── 控制面（App 层唯一入口） ─────────────────────────────────────

    def cancel_run(self, thread_id: str, run_id: str | None = None) -> bool:
        """取消 Run：run_id 必须匹配活动 Run（绑定防串线）。"""
        session = self.manager.get_session(thread_id)
        if session is None or session.active_run_id is None:
            return False
        if run_id is not None and session.active_run_id != run_id:
            return False
        runner = self._runner_for(thread_id)
        if runner is None:
            return False
        cancel = getattr(runner, "cancel_run", None)
        if not callable(cancel):
            return False
        cancel()
        return True

    def steer(self, thread_id: str, text: str, *, message_id: str = "") -> bool:
        """立即输入注入（下一安全检查点生效）。"""
        runner = self._runner_for(thread_id)
        if runner is None:
            return False
        steer = getattr(runner, "steer", None)
        if not callable(steer):
            return False
        try:
            steer(text, message_id=message_id)
        except TypeError:
            steer(text)  # 旧 API 桩：只接受 text
        return True

    def _runner_for(self, thread_id: str) -> object | None:
        """runner 解析：引擎注册表优先，回退到 session.runner。"""
        runner = self._runners.get(thread_id)
        if runner is not None:
            return runner
        session = self.manager.get_session(thread_id)
        return getattr(session, "runner", None) if session is not None else None

    def permit_tool(self, thread_id: str, run_id: str, tool_call_id: str) -> bool:
        """审批通过：thread/run 绑定校验后放行。"""
        session = self.manager.get_session(thread_id)
        if session is None or session.active_run_id != run_id:
            return False
        runner = self._runner_for(thread_id)
        if runner is None:
            return False
        permit = getattr(runner, "permit_tool", None)
        if callable(permit):
            permit(tool_call_id)
            return True
        inbound = getattr(runner, "inbound", None)
        old_permit = getattr(inbound, "permit", None)
        if callable(old_permit):
            old_permit(tool_call_id)
            return True
        return False

    def deny_tool(
        self, thread_id: str, run_id: str, tool_call_id: str, *, reason: str = ""
    ) -> bool:
        """审批拒绝：thread/run 绑定校验后拒绝。"""
        session = self.manager.get_session(thread_id)
        if session is None or session.active_run_id != run_id:
            return False
        runner = self._runner_for(thread_id)
        if runner is None:
            return False
        deny = getattr(runner, "deny_tool", None)
        if callable(deny):
            deny(tool_call_id, reason=reason)
            return True
        inbound = getattr(runner, "inbound", None)
        old_deny = getattr(inbound, "deny", None)
        if callable(old_deny):
            old_deny(tool_call_id, reason=reason)
            return True
        return False

    # ── 输入 ─────────────────────────────────────────────────────────

    async def send_input(self, message: InputMessage) -> InputReceipt:
        """输入路由（幂等 message_id 重放由 manager 保证）。"""
        return await self.manager.send_input(message)

    # ── 统一 Run 循环 ────────────────────────────────────────────────

    async def run_loop(
        self,
        thread_id: str,
        runner: object,
        text: str,
        *,
        emitter: Emitter,
        on_approval: ApprovalHook | None = None,
        needs_permit: Callable[[ToolCallBegin], bool] | None = None,
        before_finish: FinishHook | None = None,
        on_finish: FinishHook | None = None,
    ) -> str:
        """驱动一次完整 Run（唯一实现），返回终态：completed/cancelled/failed。

        - 事件经 emitter 输出，seq 由 manager 统一分配。
        - 精细相位（RUNNING_MODEL/RUNNING_TOOL/WAITING_APPROVAL）在此声明。
        - ``before_finish``：终态转换前回调（settle 立即输入等）。
        - 结束统一走 manager 终态转换（complete/cancel/fail）+ workspace
          释放 + 审批过期 + on_finish 回调。
        """
        run_id = ""
        stop_reason: str | None = None
        cancelled = False
        pending_approval: str | None = None
        error: BaseException | None = None

        # return_type 默认即 "event"（LoopAdapter.run）；不显式传参以兼容
        # 只接受 prompt 的 runner 桩（BlockingRunner 等）。
        # try/finally：任何退出路径（成功/取消/异常）都统一走终态转换，
        # 异常在标记终态后重新抛出（由调用方记录/上报）。
        try:
            async for event in runner.run(text):
                session = self.manager.get_session(thread_id)
                run_id = session.active_run_id if session is not None else ""
                seq = session.next_seq() if session is not None else 0

                if isinstance(event, TurnResult):
                    await self._declare_phase(thread_id, run_id, RunPhase.RUNNING_TOOL)
                elif isinstance(event, RunEnd):
                    stop_reason = getattr(event, "stop_reason", None)
                    await self._declare_phase(thread_id, run_id, RunPhase.RUNNING)
                elif isinstance(event, ToolCallBegin):
                    if (
                        needs_permit is not None
                        and needs_permit(event)
                        and on_approval is not None
                    ):
                        pending_approval = event.tool_call_id
                        await self._declare_phase(
                            thread_id, run_id, RunPhase.WAITING_APPROVAL
                        )
                        await on_approval(thread_id, run_id, event)
                    elif pending_approval is not None:
                        pending_approval = None

                emitted = emitter(thread_id, run_id or None, event, seq)
                if asyncio.iscoroutine(emitted):
                    await emitted
        except asyncio.CancelledError as exc:
            cancelled = True
            error = exc
        except Exception as exc:  # noqa: BLE001 — 标记 FAILED 后重新抛出
            stop_reason = "error"
            error = exc
        finally:
            if stop_reason == "cancelled":
                cancelled = True
            outcome = "completed"
            if cancelled:
                outcome = "cancelled"
            elif error is not None:
                outcome = "failed"
            if before_finish is not None:
                await before_finish(thread_id, run_id, outcome)
            await self._finish_run(
                thread_id,
                run_id,
                outcome,
                on_finish=on_finish,
            )
        if error is not None:
            raise error
        return outcome

    # ── 内部 ─────────────────────────────────────────────────────────

    async def _declare_phase(
        self, thread_id: str, run_id: str, phase: RunPhase
    ) -> None:
        """精细相位声明（集中转换表门控；失败静默——相位只是可观测信号）。"""
        if run_id:
            await self.manager.update_run_phase(thread_id, run_id, phase)

    async def _finish_run(
        self,
        thread_id: str,
        run_id: str,
        outcome: str,
        *,
        on_finish: FinishHook | None = None,
    ) -> None:
        """统一终态处理：terminal 转换 → 释放 lease → 过期审批 → 回调。"""
        session = self.manager.get_session(thread_id)
        if session is None or session.active_run_id != run_id:
            return
        if outcome == "completed":
            await self.manager.complete_run(thread_id, run_id)
        elif outcome == "cancelled":
            await self.manager.cancel_run(thread_id, run_id)
        else:
            await self.manager.fail_run(thread_id, run_id)
        await self.manager.release_workspace(thread_id, run_id)
        if on_finish is not None:
            await on_finish(thread_id, run_id, outcome)

    # ── 快照与清理 ───────────────────────────────────────────────────

    async def snapshot(self, thread_id: str) -> dict:
        return await self.manager.get_snapshot(thread_id)

    async def close(self) -> None:
        """取消所有活动 Run 任务并清空注册表。"""
        for task in list(self._tasks.values()):
            if not task.done():
                task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
        self._runners.clear()

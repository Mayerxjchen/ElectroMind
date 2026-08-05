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
from pathlib import Path

from ..artifacts.manifest import ArtifactManifest
from ..artifacts.registry import ArtifactRegistry
from ..core.events import RunEnd, ToolCallBegin, TurnResult
from ..execution.plan import PlanState, PlanStep, PlanStore, PlanTracker, StepStatus
from ..harness import InputMessage, InputReceipt, ThreadSessionManager
from ..harness.state import RunPhase

# emitter 签名：emit(thread_id, run_id, event, seq) -> None | Awaitable[None]
Emitter = Callable[[str, str | None, object, int], "None | Awaitable[None]"]
# 审批请求回调：on_approval(thread_id, run_id, event) -> Awaitable
ApprovalHook = Callable[[str, str, ToolCallBegin], Awaitable[None]]
# 结束后回调：on_finish(thread_id, run_id, outcome) -> Awaitable
FinishHook = Callable[[str, str, str], Awaitable[None]]
# 领域状态变更回调（G1）：emit(thread_id, "plan"|"artifact", payload)。
# 同步契约：App 层（wire _emit_jsonrpc / CLI client）挂接时不得返回协程。
StateEmitter = Callable[[str, str, dict], None]


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

    # ── G1: per-thread Plan / Artifact 领域状态 ──────────────────────
    # PlanTracker（内存当前态）+ PlanStore（<thread>/plans/ 磁盘，含版本历史）；
    # ArtifactRegistry（<thread>/artifacts.jsonl 磁盘）。惰性初始化并按需恢复。
    _plan_trackers: dict[str, PlanTracker] = field(default_factory=dict)
    _active_plan_ids: dict[str, str] = field(default_factory=dict)
    _artifact_registries: dict[str, ArtifactRegistry] = field(default_factory=dict)
    # 领域状态变更回调：emit(thread_id, "plan"|"artifact", payload)。
    # 由 App 层（wire / CLI client）挂接，把变更推送为 plan/state、artifact/state。
    state_emitter: StateEmitter | None = None

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

    # ── Plan 领域状态（G1） ───────────────────────────────────────────
    # 状态事实源：PlanTracker（进程内）+ PlanStore（磁盘，含版本历史）。
    # 所有变更经 state_emitter 推送为 plan/state；非法转换直接抛
    # ValueError（StepTransitionError / 版本门），由 App 层转述。

    def plan_state(self, thread_id: str) -> PlanState | None:
        """当前计划（无则 None）；首次访问按磁盘最新版本恢复。"""
        return self._ensure_plan(thread_id).current

    def plan_propose(self, thread_id: str, plan: PlanState) -> PlanState:
        """提议新计划：冻结为 READY、落盘、推送 plan/state。

        已批准版本不可原地覆盖（PlanTracker 版本门）；需 revise 提版本。
        """
        tracker = self._ensure_plan(thread_id)
        proposed = tracker.propose(plan)
        self._active_plan_ids[thread_id] = plan.plan_id
        self._plan_store(thread_id).save(proposed)
        self._emit_state(thread_id, "plan", {"plan": proposed.to_dict()})
        return proposed

    def plan_approve(self, thread_id: str) -> PlanState | None:
        """批准当前 READY 计划（冻结为 APPROVED；非 READY 无操作）。"""
        tracker = self._ensure_plan(thread_id)
        approved = tracker.approve()
        if approved is not None:
            self._plan_store(thread_id).save(approved)
            self._emit_state(thread_id, "plan", {"plan": approved.to_dict()})
        return approved

    def plan_revise(self, thread_id: str) -> PlanState | None:
        """开始新修订（version+1 → REVISING）；批准版本不被修改。"""
        tracker = self._ensure_plan(thread_id)
        revised = tracker.revise()
        if revised is not None:
            self._plan_store(thread_id).save(revised)
            self._emit_state(thread_id, "plan", {"plan": revised.to_dict()})
        return revised

    def plan_cancel(self, thread_id: str) -> PlanState | None:
        """取消当前计划（CANCELLED，保留在磁盘）。"""
        tracker = self._ensure_plan(thread_id)
        cancelled = tracker.cancel()
        if cancelled is not None:
            self._plan_store(thread_id).save(cancelled)
            self._emit_state(thread_id, "plan", {"plan": cancelled.to_dict()})
        return cancelled

    def plan_update_step(
        self,
        thread_id: str,
        step_id: str,
        status: StepStatus,
        *,
        step: PlanStep | None = None,
    ) -> PlanState | None:
        """推进步骤状态；COMPLETED 缺 Evidence / VERIFIED 缺验证器记录拒绝。"""
        tracker = self._ensure_plan(thread_id)
        updated = tracker.update_step(step_id, status, step=step)
        if updated is not None:
            self._plan_store(thread_id).save(updated)
            self._emit_state(thread_id, "plan", {"plan": updated.to_dict()})
        return updated

    # ── Artifact 领域状态（G1） ───────────────────────────────────────

    def artifacts(self, thread_id: str) -> list[ArtifactManifest]:
        """全部 Artifact Manifest（含状态，按 id 索引）。"""
        return self._ensure_artifacts(thread_id).all()

    def artifact_register(
        self, thread_id: str, manifest: ArtifactManifest
    ) -> ArtifactManifest:
        """登记新产物（CREATED）；同 id 内容变化记录 replace 事件。"""
        registry = self._ensure_artifacts(thread_id)
        stored = registry.register(manifest)
        self._emit_state(thread_id, "artifact", {"artifact": stored.to_dict()})
        return stored

    def artifact_complete(
        self, thread_id: str, artifact_id: str, *, who: str = "runner"
    ) -> ArtifactManifest | None:
        """程序正常结束 → COMPLETED（绝不自动 VALIDATED）。"""
        return self._artifact_transition(thread_id, artifact_id, "complete", who=who)

    def artifact_validate(
        self,
        thread_id: str,
        artifact_id: str,
        *,
        parser: str,
        who: str = "",
    ) -> ArtifactManifest | None:
        """确定性 Parser 通过 → VALIDATED（必须记录解析器名）。"""
        return self._artifact_transition(
            thread_id, artifact_id, "validate", parser=parser, who=who
        )

    def artifact_validate_fail(
        self, thread_id: str, artifact_id: str, *, reason: str
    ) -> ArtifactManifest | None:
        """R2-9: 解析失败 → validation=REJECTED（acceptance 保持 COMPLETED）。"""
        return self._artifact_transition(
            thread_id, artifact_id, "reject_validation", reason=reason
        )

    def artifact_accept(
        self, thread_id: str, artifact_id: str, *, who: str, role: str = "user"
    ) -> ArtifactManifest | None:
        """用户/独立 Reviewer 确认 → ACCEPTED（创建者不能自证；P0-6 角色门）。"""
        return self._artifact_transition(
            thread_id, artifact_id, "accept", who=who, role=role
        )

    def artifact_reject(
        self, thread_id: str, artifact_id: str, *, reason: str
    ) -> ArtifactManifest | None:
        """检查失败 → REJECTED（必须记录原因）。"""
        return self._artifact_transition(
            thread_id, artifact_id, "reject", reason=reason
        )

    # ── 内部：Plan / Artifact 惰性初始化与推送 ───────────────────────

    def _thread_root(self, thread_id: str) -> Path:
        """thread 数据目录（与 Thread.open / session show 同源）。"""
        from ..paths import default_electromind_home

        return default_electromind_home() / "threads" / thread_id

    def _plan_store(self, thread_id: str) -> PlanStore:
        return PlanStore(self._thread_root(thread_id))

    def _ensure_plan(self, thread_id: str) -> PlanTracker:
        tracker = self._plan_trackers.get(thread_id)
        if tracker is None:
            tracker = PlanTracker()
            # R2-7: 恢复按活跃 plan_id（propose 时记录）或磁盘最新版本，
            # 不再硬编码 "default"。
            plan_id = self._active_plan_ids.get(thread_id)
            latest = None
            if plan_id is not None:
                latest = self._plan_store(thread_id).latest(plan_id)
            if latest is None:
                store_ids = self._plan_store(thread_id).list_ids()
                if store_ids:
                    latest = self._plan_store(thread_id).latest(store_ids[-1])
            if latest is not None:
                tracker.restore(latest)
                self._active_plan_ids[thread_id] = latest.plan_id
            self._plan_trackers[thread_id] = tracker
        return tracker

    def _ensure_artifacts(self, thread_id: str) -> ArtifactRegistry:
        registry = self._artifact_registries.get(thread_id)
        if registry is None:
            registry = ArtifactRegistry(
                self._thread_root(thread_id) / "artifacts.jsonl"
            )
            self._artifact_registries[thread_id] = registry
        return registry

    def _artifact_transition(
        self, thread_id: str, artifact_id: str, action: str, **kwargs
    ) -> ArtifactManifest | None:
        registry = self._ensure_artifacts(thread_id)
        manifest = registry.get(artifact_id)
        if manifest is None:
            return None
        updated = getattr(manifest, action)(**kwargs)
        registry.register(updated)  # 同 sha256 → 原地覆盖 + flush
        self._emit_state(thread_id, "artifact", {"artifact": updated.to_dict()})
        return updated

    def _emit_state(self, thread_id: str, kind: str, payload: dict) -> None:
        """领域状态变更推送（App 层经 state_emitter 编码为事件）。"""
        if self.state_emitter is None:
            return
        self.state_emitter(thread_id, kind, payload)

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
                # P0-5: 副作用 intent 需要 run_id（恢复锚点）
                setattr(runner, "current_run_id", run_id)
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

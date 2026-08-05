"""Runner —— 带语义检查点控制面 + tool hooks 的完整 Agent Runner。

继承 `BaseRunner`（从而继承 `LoopAdapter` 的循环骨架与持久化），叠加两个
能力：

- **语义检查点控制面**（M1 统一）：steer / cancel 走
  ``harness/checkpoints.InboundCheckpoint``，在循环的六个命名检查点
  （RUN_STARTED / BEFORE_MODEL / AFTER_MODEL / BEFORE_TOOL_BATCH /
  AFTER_TOOL_BATCH / BEFORE_FINALIZE）统一处理；permit / deny 仍走
  ``InboundMailbox``（工具审批是等待语义，与检查点注入无关）。
- **tool hooks**：`emit_tool_events` 走 `run_tool_with_hooks`（before/after）。

`Runner` 与 thread 同生共死：`await Runner.create(...)` → 多次
`runner.run(user_input)` → `await runner.close()`。
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Sequence
from pathlib import Path

from ..conversation import ConversationStore
from ..core.agent import Agent
from ..core.events import RunEnd, ToolCallBegin, ToolResult, TurnEnd
from ..core.message import Message, Messages, ToolCall
from ..core.provider import ProviderProtocol
from ..core.tool import FunctionTool, ToolOutput
from ..harness.checkpoints import (
    CheckpointDrain,
    CheckpointKind,
    InboundCheckpoint,
)
from ..harness.inbound import InputDelivery, InputMessage
from ..sandbox import Sandbox
from ..skills import SkillRegistry
from ..skills.runtime import SkillRuntime
from .base_runner import (
    BaseRunner,
    _run_capabilities,
    _with_context_manager,
    assemble_run_resources,
)
from .helper import append_message
from .hooks import PostToolHookContext, ToolHookContext, ToolHooks
from .inbound import (
    CancelRun,
    DenyTool,
    InboundMailbox,
    PermitTool,
    RunCancelled,
    ToolPermitResult,
)
from .loop_core import run_event_loop
from .run_state import RunState
from .thread import Thread


class Runner(BaseRunner):
    """Run 调度器，与 thread 同生共死。

    `await Runner.create(...)` → 多次 `runner.run(user_input)` → `await runner.close()`
    """

    def __init__(
        self,
        *,
        thread: Thread,
        sandbox: Sandbox,
        store: ConversationStore,
        messages: Messages,
        agent: Agent,
        skills: SkillRegistry,
        conversation_id: str,
        inbound: InboundMailbox | None = None,
        checkpoint_policy: object | None = None,  # 保留兼容参数（已废弃语义）
        tool_hooks: ToolHooks | None = None,
        skill_runtime: SkillRuntime | None = None,
    ):
        super().__init__(
            agent,
            thread,
            store=store,
            messages=messages,
            sandbox=sandbox,
            skills=skills,
            skill_runtime=skill_runtime,
        )
        self.conversation_id = conversation_id
        # M1: steer/cancel 走语义检查点；permit/deny 仍走邮箱
        self.inbound_checkpoint = InboundCheckpoint()
        self.inbound = inbound or InboundMailbox()
        self.tool_hooks = tool_hooks
        # P0-1/P0-5: 每 Thread 绑定的执行状态存储（thread 目录）
        self.plan_store = _bind_plan_store(thread)
        self.artifact_registry = _bind_artifact_registry(thread)
        self.idempotency_store = _bind_idempotency_store(thread)
        self.intent_log = _bind_intent_log(thread)
        # 当前 Run id（由 RunEngine 在 run_loop 开始时设置）
        self.current_run_id = ""
        # P0-4: 已批准工具调用的参数摘要（tool_call_id → digest）；
        # 执行时校验参数未被篡改。
        self.approved_arguments: dict[str, str] = {}

    def record_approved_arguments(self, tool_call_id: str, digest: str) -> None:
        """记录审批通过的参数摘要（wire permit 解析后调用）。"""
        if digest:
            self.approved_arguments[tool_call_id] = digest

    def check_approved_arguments(self, tool_call_id: str, digest: str) -> bool:
        """执行时校验：已批准的调用参数必须与审批时一致。"""
        expected = self.approved_arguments.get(tool_call_id)
        if expected is None:
            return True  # 未走审批路径（auto 模式）不校验
        return expected == digest

    def steer(self, text: str, *, message_id: str = "") -> None:
        message = InputMessage(
            message_id=message_id or f"steer-{id(self)}",
            thread_id=str(getattr(self.thread, "id", "")),
            target_run_id=None,
            text=text,
            delivery=InputDelivery.IMMEDIATE,
            created_at="",
        )
        self.inbound_checkpoint.submit_immediate(message)

    def cancel_run(self) -> None:
        self.inbound_checkpoint.request_cancel()

    def permit_tool(self, tool_call_id: str) -> None:
        self.inbound.permit(tool_call_id)

    def deny_tool(self, tool_call_id: str, *, reason: str = "") -> None:
        self.inbound.deny(tool_call_id, reason=reason)

    async def wait_tool_permit(self, tool_call_id: str) -> ToolPermitResult:
        """阻塞直到入站 ``PermitTool`` / ``DenyTool`` / ``CancelRun``。"""
        deferred: list[object] = []
        try:
            while True:
                event = await self.inbound.wait()
                resolved = self._resolve_tool_permit(event, tool_call_id)
                if resolved is not None:
                    return resolved
                deferred.append(event)
        finally:
            for event in deferred:
                self.inbound.push(event)

    @staticmethod
    def _resolve_tool_permit(
        event: object, tool_call_id: str
    ) -> ToolPermitResult | None:
        if isinstance(event, PermitTool):
            if event.tool_call_id == tool_call_id:
                return ToolPermitResult(approved=True)
            return None
        if isinstance(event, DenyTool):
            if event.tool_call_id == tool_call_id:
                return ToolPermitResult(approved=False, reason=event.reason)
            return None
        if isinstance(event, CancelRun):
            return ToolPermitResult(
                approved=False,
                reason="run cancelled by user",
            )
        return None

    def _apply_inbound_drain(
        self, outbound_event: object, *, turn_id: int, turn: int
    ) -> None:
        # 旧事件类型轮询检查点 —— M1 起废弃：由 checkpoints.InboundCheckpoint
        # 的六个命名语义检查点取代。此方法仅保留签名以兼容外部调用。
        del outbound_event, turn_id, turn
        return

    async def checkpoint(
        self,
        kind: CheckpointKind,
        tool_call_ids: list[str] | None = None,
    ) -> CheckpointDrain | None:
        """语义检查点：drain 立即输入与取消请求。

        BEFORE_TOOL_BATCH 时登记批次工具 id（取消时产出合成取消结果所需）。
        """
        if kind == CheckpointKind.BEFORE_TOOL_BATCH and tool_call_ids is not None:
            self.inbound_checkpoint.begin_tool_batch(tool_call_ids)
        drain = self.inbound_checkpoint.checkpoint(kind)
        if kind == CheckpointKind.AFTER_TOOL_BATCH:
            self.inbound_checkpoint.end_tool_batch()
        return drain

    async def emit(
        self,
        event,
        *,
        turn_id: int,
        turn: int,
    ) -> AsyncGenerator:
        del turn_id, turn
        yield event

    async def emit_tool_events(
        self,
        tool_calls: list[ToolCall],
        turn_id: int,
        turn: int,
    ) -> AsyncGenerator:
        """P0-3: ToolScheduler 接入 —— 只读调用并行，其余串行。

        事件与结果保持模型调用的原始顺序（ToolCallBegin/ToolResult 配对
        完整）；批内只读调用并行执行，批间严格串行。无法判定 effect 的
        调用（未知名工具）保守串行。
        """
        del turn
        from ..execution.tool_scheduler import ToolCallInfo, ToolScheduler

        scheduler = ToolScheduler()
        infos: list[ToolCallInfo] = []
        for tool_call in tool_calls:
            name = tool_call.name
            tool = self.agent.tool_map.get(name)
            effect = getattr(tool, "effect", None) if tool is not None else None
            arguments = tool_call.arguments
            if not isinstance(arguments, str):
                arguments = str(arguments)
            infos.append(
                ToolCallInfo(
                    tool_call_id=tool_call.id,
                    name=name,
                    arguments=_parse_call_arguments(arguments),
                    effect=effect,
                )
            )

        for batch in scheduler.plan(infos):
            # 1) 按原顺序产出 ToolCallBegin
            for info in batch:
                yield ToolCallBegin(
                    info.tool_call_id, info.name, _dump_arguments(info.arguments)
                )
            # 2) 批内并行执行（结果按输入顺序）；副作用工具带
            #    intent→commit→reconcile 记录与幂等提交。
            results = await scheduler.execute_batch(
                batch,
                lambda info: self._execute_with_intent(info, turn_id=turn_id),
            )
            # 3) 按原顺序 append 消息并产出 ToolResult
            for info, entry in zip(batch, results):
                output = entry["result"]
                append_message(
                    self.messages,
                    Message.tool_result(info.tool_call_id, output.content),
                    turn_id=turn_id,
                )
                yield ToolResult(
                    info.tool_call_id, info.name, output.content, ok=output.ok
                )

    async def execute_tool(self, tool_call: ToolCall) -> ToolOutput:
        """P0-6: 帧级工具调用预算 —— 执行前计数与拒绝（无法阻止事后
        超额副作用，必须在执行前硬限）。"""
        limit = getattr(self.frame, "max_tool_calls", 0) or 0
        if limit > 0 and getattr(self.frame, "tool_calls_executed", 0) >= limit:
            return ToolOutput.fail(
                f"子 agent 工具调用预算已超限（上限 {limit}，执行前拒绝）"
            )
        self.frame.tool_calls_executed += 1
        return await super().execute_tool(tool_call)

    async def _execute_with_intent(self, info, *, turn_id: int) -> ToolOutput:
        """P0-5: 副作用工具执行包装 —— intent→commit→reconcile + 幂等提交。

        - 执行前记录 intent（进程在此后终止 → 恢复锚点）。
        - SUBMIT_EXTERNAL 先查 IdempotencyStore：同 key 已成功 → 重放原结果。
        - 成功后 commit（结果引用入库）；失败/异常 → reconcile（不盲重试）。
        """
        from ..execution.effects import ToolEffect
        from ..execution.idempotency import IdempotencyKey

        side_effects = {
            ToolEffect.WRITE_WORKSPACE,
            ToolEffect.WRITE_HOST,
            ToolEffect.EXECUTE,
            ToolEffect.SUBMIT_EXTERNAL,
            ToolEffect.DESTRUCTIVE,
        }
        hook_ctx = ToolHookContext(
            self,
            info.tool_call_id,
            info.name,
            _dump_arguments(info.arguments),
            turn_id,
        )
        tool_call = _tool_call_from_info(info)

        if info.effect not in side_effects:
            return await self.run_tool_with_hooks(hook_ctx, tool_call)

        args_digest = _arguments_digest(_dump_arguments(info.arguments))
        # 幂等提交：外部提交类先查已记录结果
        if info.effect == ToolEffect.SUBMIT_EXTERNAL:
            key = IdempotencyKey.derive(
                run_id=self.current_run_id,
                tool_name=info.name,
                args=info.arguments,
            )
            if self.idempotency_store.is_duplicate(key):
                replay = self.idempotency_store.get_result(key)
                if replay is not None:
                    return ToolOutput.succeed(replay)

        intent = self.intent_log.record(
            run_id=self.current_run_id,
            tool_call_id=info.tool_call_id,
            tool=info.name,
            arguments_digest=args_digest,
        )
        try:
            output = await self.run_tool_with_hooks(hook_ctx, tool_call)
        except BaseException:
            self.intent_log.reconcile(intent.intent_id)
            raise
        if output.ok:
            self.intent_log.commit(
                intent.intent_id, result_ref=str(output.content)[:200]
            )
            if info.effect == ToolEffect.SUBMIT_EXTERNAL:
                self.idempotency_store.record_completed(
                    IdempotencyKey.derive(
                        run_id=self.current_run_id,
                        tool_name=info.name,
                        args=info.arguments,
                    ),
                    str(output.content),
                )
        else:
            self.intent_log.reconcile(intent.intent_id)
        return output

    async def run_tool_with_hooks(
        self,
        ctx: ToolHookContext,
        tool_call: ToolCall,
    ) -> ToolOutput:
        if self.tool_hooks is not None:
            decision = await self.tool_hooks.run_before(ctx)
            if decision is not None:
                return ToolOutput(
                    content=decision.content or "",
                    ok=decision.ok,
                )

        output = await self.execute_tool(tool_call)

        if self.tool_hooks is None:
            return output

        post_ctx = PostToolHookContext(
            ctx.runner,
            ctx.tool_call_id,
            ctx.name,
            ctx.arguments,
            ctx.turn_id,
            output,
        )
        return await self.tool_hooks.run_after(post_ctx, output)

    async def _event_source(
        self,
        user_input: str,
        turn_id: int,
        **run_kwargs,
    ) -> AsyncGenerator:
        try:
            async for event in run_event_loop(
                self,
                user_input=user_input,
                turn_id=turn_id,
                **run_kwargs,
            ):
                yield event
        except RunCancelled as exc:
            self.run_state.turn = exc.turn
            self.run_state.stop_reason = "cancelled"
            self.run_state.phase = "ended"
            yield TurnEnd(exc.turn, stopped=True, stop_reason="cancelled")
            yield RunEnd(exc.turn, stop_reason="cancelled")
            self.run_state.phase = "tearing_down"
            self.messages.complete_orphan_tool_results(text="已取消：任务被中断")
            self.flush_conversation()
            self.run_state.phase = "ended"

    @classmethod
    async def create(
        cls,
        thread_id: str,
        provider: ProviderProtocol,
        *,
        overrides: dict | None = None,
        extra_system: str = "",
        max_turns: int = 24,
        skill_roots: Sequence[str | Path] = (),
        tools: Sequence[FunctionTool] = (),
        tool_hooks: ToolHooks | None = None,
    ) -> Runner:
        """创建完整 Runner：打开 thread、sandbox、conversation 和 skills。"""
        thread = Thread.open(thread_id, overrides=overrides)
        run_state = RunState(phase="waking_sandbox")
        resources = await assemble_run_resources(
            thread,
            skill_roots=skill_roots,
            tools=tools,
            extra_system=extra_system,
            run_state=run_state,
        )
        store = thread.open_store()
        conversation_id = thread.messages_conversation_id
        messages = thread.load_messages()

        # Phase-2: runtime SHARES the catalog service used at assembly time
        # (same generation) and lazily mounts activated skills into the
        # sandbox (backend-appropriate mounter).
        from ..skills.mounting import LazySkillMounter, SshLazySkillMounter
        from ..skills.snapstore import PrivateSnapshotStore

        _store = PrivateSnapshotStore()
        _mounter = None
        if resources.sandbox is not None:
            _backend = getattr(resources.sandbox, "backend", None)
            backend_name = getattr(getattr(_backend, "__class__", None), "__name__", "")
            if backend_name == "SshBackend":
                _mounter = SshLazySkillMounter(resources.sandbox, store=_store)
            else:
                _mounter = LazySkillMounter(resources.sandbox, store=_store)
        skill_runtime = SkillRuntime(
            thread.spec.project_path,
            configured_roots=tuple(thread.spec.skills) + tuple(skill_roots),
            mounter=_mounter,
            service=resources.catalog_service,
            capabilities=_run_capabilities(thread.spec),
        )
        skill_runtime.prepare_turn()

        runner = cls(
            thread=thread,
            sandbox=resources.sandbox,
            store=store,
            messages=messages,
            agent=Agent(
                provider,
                system=resources.system_prompt,
                tools=resources.tools,
                max_turns=max_turns,
                # P0-2: 正式 Runner 注入 ContextManager（85% 预算门禁）
                **_with_context_manager({}, thread.spec),
            ),
            skills=resources.skills,
            conversation_id=conversation_id,
            tool_hooks=tool_hooks,
            skill_runtime=skill_runtime,
        )
        runner.run_state = run_state
        return runner


def _bind_plan_store(thread) -> "object":
    from ..execution.plan import PlanStore

    root = getattr(thread, "root", None)
    return (
        PlanStore(Path(root) / "plans")
        if root is not None
        else PlanStore(Path.cwd() / "plans")
    )


def _bind_artifact_registry(thread) -> "object":
    from ..artifacts import ArtifactRegistry

    root = getattr(thread, "root", None)
    return (
        ArtifactRegistry(Path(root) / "artifacts.jsonl")
        if root is not None
        else ArtifactRegistry(Path.cwd() / "artifacts.jsonl")
    )


def _bind_idempotency_store(thread) -> "object":
    from ..execution.idempotency import IdempotencyStore

    root = getattr(thread, "root", None)
    return (
        IdempotencyStore(Path(root) / "idempotency.jsonl")
        if root is not None
        else IdempotencyStore(Path.cwd() / "idempotency.jsonl")
    )


def _bind_intent_log(thread) -> "object":
    from ..execution.intent_log import IntentLog

    root = getattr(thread, "root", None)
    return (
        IntentLog(Path(root) / "intent_log.jsonl")
        if root is not None
        else IntentLog(Path.cwd() / "intent_log.jsonl")
    )


def _parse_call_arguments(arguments: str) -> dict:
    """解析工具参数为 dict（供调度器资源键使用）；失败返回空 dict。"""
    try:
        parsed = json.loads(arguments)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _dump_arguments(arguments: dict) -> str:
    """把 dict 参数还原为 JSON 字符串（事件与工具调用原文一致）。"""
    return json.dumps(arguments, ensure_ascii=False, sort_keys=True)


def _arguments_digest(arguments: str) -> str:
    """参数摘要（sha256 of sorted JSON）—— intent/审批绑定共用。"""
    import hashlib

    try:
        normalized = json.dumps(
            json.loads(arguments), ensure_ascii=False, sort_keys=True
        )
    except (json.JSONDecodeError, TypeError):
        normalized = str(arguments)
    return hashlib.sha256(normalized.encode()).hexdigest()


def _tool_call_from_info(info) -> ToolCall:
    """由调度信息重建 ToolCall（执行入口需要 ToolCall 形状）。"""
    return ToolCall(
        type="function",
        id=info.tool_call_id,
        name=info.name,
        arguments=_dump_arguments(info.arguments),
    )

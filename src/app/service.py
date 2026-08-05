"""Application Service — CLI/Wire/HTTP 共用的唯一入口（M1）。

App 层只与 ``ApplicationService`` 交互；它内部驱动 ``RunEngine``
（唯一 Run 状态机）。cancel/permit/deny/steer 不再直接触碰
``runner.inbound``。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from electromind.engine import RunEngine
from electromind.harness import InputDelivery, InputMessage, InputReceipt


@dataclass(slots=True)
class ApplicationService:
    """进程级共享的 Application Service。

    ``engine`` 持有唯一 ThreadSessionManager；所有入口（wire / http /
    embedded client）共用同一个实例以保证状态事实源唯一。
    """

    engine: RunEngine = field(default_factory=RunEngine)

    # ── 输入 ─────────────────────────────────────────────────────────

    async def send_input(
        self,
        thread_id: str,
        text: str,
        *,
        delivery: InputDelivery = InputDelivery.AUTO,
        target_run_id: str | None = None,
        requested_mode=None,
        requested_model: str | None = None,
        requested_max_iterations: int | None = None,
    ) -> InputReceipt:
        """路由用户输入（幂等 message_id 由 manager 保证）。"""
        message = InputMessage.create(
            thread_id,
            text,
            target_run_id=target_run_id,
            delivery=delivery,
            requested_mode=requested_mode,
            requested_model=requested_model,
            requested_max_iterations=requested_max_iterations,
        )
        return await self.engine.send_input(message)

    # ── 控制面 ───────────────────────────────────────────────────────

    def cancel_run(self, thread_id: str, run_id: str | None = None) -> bool:
        return self.engine.cancel_run(thread_id, run_id)

    def steer(self, thread_id: str, text: str, *, message_id: str = "") -> bool:
        return self.engine.steer(thread_id, text, message_id=message_id)

    def permit_tool(self, thread_id: str, run_id: str, tool_call_id: str) -> bool:
        return self.engine.permit_tool(thread_id, run_id, tool_call_id)

    def deny_tool(
        self, thread_id: str, run_id: str, tool_call_id: str, *, reason: str = ""
    ) -> bool:
        return self.engine.deny_tool(thread_id, run_id, tool_call_id, reason=reason)

    # ── Runner 注册 ──────────────────────────────────────────────────

    def register_runner(self, thread_id: str, runner: object) -> None:
        self.engine.register_runner(thread_id, runner)

    def unregister_runner(self, thread_id: str) -> None:
        self.engine.unregister_runner(thread_id)

    def runner_for(self, thread_id: str) -> object | None:
        return self.engine.runner_for(thread_id)

    # ── 查询 ─────────────────────────────────────────────────────────

    async def snapshot(self, thread_id: str) -> dict:
        return await self.engine.snapshot(thread_id)

    def has_active_run(self, thread_id: str) -> bool:
        return self.engine.manager.has_active_run(thread_id)

    async def close(self) -> None:
        await self.engine.close()


# 进程级共享单例（wire/http/embedded 共用）
_service: ApplicationService | None = None


def get_application_service(manager=None) -> ApplicationService:
    """返回进程级共享的 Application Service（惰性创建）。

    ``manager`` 提供时（wire 的 ``_harness_manager``）复用同一
    ThreadSessionManager，保证状态事实源唯一。
    """
    global _service
    if _service is None:
        if manager is not None:
            from electromind.engine import RunEngine

            _service = ApplicationService(engine=RunEngine(manager=manager))
        else:
            _service = ApplicationService()
    return _service


def reset_application_service() -> None:
    """测试用：重置进程级单例。"""
    global _service
    _service = None

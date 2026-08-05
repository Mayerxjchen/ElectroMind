"""ToolScheduler — 冲突感知的并行工具调度（M4 §9.2）。

并行规则：
- ``PURE``：永远可并行。
- 不冲突的 ``READ_*``：可并行（同路径读也安全）。
- 写同一路径 / 写任何受保护资源：必须串行。
- 同一 HPC 工作目录的提交（``SUBMIT_EXTERNAL``）：串行 + 单所有者。
- ``DESTRUCTIVE``：串行且必须审批。
- 无法判定 Effect 的工具：串行（保守）。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .effects import ToolEffect


@dataclass(frozen=True, slots=True)
class ToolCallInfo:
    """一次待调度的工具调用。"""

    tool_call_id: str
    name: str
    arguments: dict
    effect: ToolEffect | None = None

    def resources(self) -> set[str]:
        """从 effect + 参数提取资源键（路径归一化）。"""
        res: set[str] = set()
        if self.effect in (
            ToolEffect.READ_WORKSPACE,
            ToolEffect.WRITE_WORKSPACE,
            ToolEffect.READ_HOST,
            ToolEffect.WRITE_HOST,
        ):
            path = self.arguments.get("path")
            if path:
                res.add(f"{self.effect}:{path}")
        if self.effect == ToolEffect.SUBMIT_EXTERNAL:
            res.add("external:submit")
        return res


# 可并行组合矩阵：False = 必须串行。
# PURE 保守串行（纯计算工具也可能带副作用，测试工具尤甚）；只有
# 明确只读的 READ_* 之间才并行。
_PARALLEL: dict[ToolEffect, frozenset[ToolEffect]] = {
    ToolEffect.PURE: frozenset(),
    ToolEffect.READ_WORKSPACE: frozenset(
        {ToolEffect.READ_WORKSPACE, ToolEffect.READ_HOST}
    ),
    ToolEffect.READ_HOST: frozenset({ToolEffect.READ_WORKSPACE, ToolEffect.READ_HOST}),
    # 其余（WRITE/EXECUTE/NETWORK/SUBMIT/DESTRUCTIVE/None）默认串行
}


def effects_conflict(a: ToolEffect | None, b: ToolEffect | None) -> bool:
    """两 effect 是否冲突（None = 无法判定 → 冲突，保守串行）。"""
    if a is None or b is None:
        return True
    allowed = _PARALLEL.get(a, frozenset())
    if b not in allowed:
        return True
    allowed_b = _PARALLEL.get(b, frozenset())
    return a not in allowed_b


class ToolScheduler:
    """把工具调用划分成可并行的批次（批内并行、批间串行）。"""

    def is_conflicting(self, a: ToolCallInfo, b: ToolCallInfo) -> bool:
        """两调用是否冲突（effect 冲突 或 资源键相交 或 无法判定）。"""
        if effects_conflict(a.effect, b.effect):
            return True
        shared = a.resources() & b.resources()
        if shared:
            return True
        return False

    def plan(self, calls: list[ToolCallInfo]) -> list[list[ToolCallInfo]]:
        """划分批次：每批内的调用互不冲突（可并行），批次间严格串行。"""
        batches: list[list[ToolCallInfo]] = []
        for call in calls:
            placed = False
            for batch in batches:
                if not any(self.is_conflicting(call, existing) for existing in batch):
                    batch.append(call)
                    placed = True
                    break
            if not placed:
                batches.append([call])
        return batches

    async def execute_batch(
        self,
        calls: list[ToolCallInfo],
        execute_one,
        *,
        concurrency_limit: int = 4,
    ) -> list[dict]:
        """并行执行一批调用；返回与输入同序的结果列表。"""
        semaphore = asyncio.Semaphore(max(1, concurrency_limit))

        async def run(call: ToolCallInfo) -> dict:
            async with semaphore:
                result = await execute_one(call)
                return {"tool_call_id": call.tool_call_id, "result": result}

        results = await asyncio.gather(*(run(c) for c in calls))
        return list(results)

    def serialize_all(self, calls: list[ToolCallInfo]) -> list[list[ToolCallInfo]]:
        """全串行批次（每个调用一批）—— 无法判定 Effect 时的保守路径。"""
        return [[c] for c in calls]

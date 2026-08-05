"""ToolIntent 日志 — 工具副作用的 intent→commit→reconcile 持久化（P0-5）。

有副作用的工具（写入/执行/外部提交）在执行前记录 intent；成功后
``committed``；失败或状态未知 → ``reconciling``（绝不盲目重试）。

进程在 ToolCallBegin 后终止时，未 committed 的 intent 是恢复的锚点：
恢复后先查 IdempotencyStore —— 已记录结果则重放，否则保持 reconciling
等待外部确认（scheduler 查询 / 人工）。
"""

from __future__ import annotations

import json
import time
from enum import StrEnum
from pathlib import Path


class IntentStatus(StrEnum):
    INTENT = "intent"  # 已声明，未执行完成
    COMMITTED = "committed"  # 副作用已确认完成（结果已记录）
    RECONCILING = "reconciling"  # 状态未知，禁止自动重试


class ToolIntent:
    """一次副作用工具的意图记录。"""

    def __init__(
        self,
        intent_id: str,
        run_id: str,
        tool_call_id: str,
        tool: str,
        arguments_digest: str,
        status: IntentStatus = IntentStatus.INTENT,
        result_ref: str = "",
        created_at: float = 0.0,
    ) -> None:
        self.intent_id = intent_id
        self.run_id = run_id
        self.tool_call_id = tool_call_id
        self.tool = tool
        self.arguments_digest = arguments_digest
        self.status = status
        self.result_ref = result_ref
        self.created_at = created_at or time.time()

    def to_dict(self) -> dict:
        return {
            "intent_id": self.intent_id,
            "run_id": self.run_id,
            "tool_call_id": self.tool_call_id,
            "tool": self.tool,
            "arguments_digest": self.arguments_digest,
            "status": str(self.status),
            "result_ref": self.result_ref,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ToolIntent":
        return cls(
            intent_id=d["intent_id"],
            run_id=d.get("run_id", ""),
            tool_call_id=d.get("tool_call_id", ""),
            tool=d.get("tool", ""),
            arguments_digest=d.get("arguments_digest", ""),
            status=IntentStatus(d.get("status", "intent")),
            result_ref=d.get("result_ref", ""),
            created_at=d.get("created_at", time.time()),
        )


class IntentLog:
    """追加式 intent 日志（JSONL，原子追加）。

    恢复语义：``pending_for(run_id)`` 返回未 committed 的 intent；
    调用方据此决定重放（有幂等结果）或进入 RECONCILING。
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._intents: dict[str, ToolIntent] = {}
        self._load()

    @staticmethod
    def new_intent_id() -> str:
        import uuid

        return f"intent-{uuid.uuid4().hex[:12]}"

    def record(
        self,
        *,
        run_id: str,
        tool_call_id: str,
        tool: str,
        arguments_digest: str,
    ) -> ToolIntent:
        """执行前记录 intent。"""
        intent = ToolIntent(
            intent_id=self.new_intent_id(),
            run_id=run_id,
            tool_call_id=tool_call_id,
            tool=tool,
            arguments_digest=arguments_digest,
        )
        self._intents[intent.intent_id] = intent
        self._flush()
        return intent

    def commit(self, intent_id: str, result_ref: str) -> ToolIntent | None:
        """副作用确认完成后提交。"""
        intent = self._intents.get(intent_id)
        if intent is None:
            return None
        intent.status = IntentStatus.COMMITTED
        intent.result_ref = result_ref
        self._flush()
        return intent

    def reconcile(self, intent_id: str) -> ToolIntent | None:
        """状态未知 → RECONCILING（禁止自动重试）。"""
        intent = self._intents.get(intent_id)
        if intent is None:
            return None
        intent.status = IntentStatus.RECONCILING
        self._flush()
        return intent

    def get(self, intent_id: str) -> ToolIntent | None:
        return self._intents.get(intent_id)

    def pending_for(self, run_id: str) -> list[ToolIntent]:
        """该 Run 未 committed 的 intent（恢复锚点）。"""
        return [
            i
            for i in self._intents.values()
            if i.run_id == run_id and i.status != IntentStatus.COMMITTED
        ]

    def committed_for(self, run_id: str) -> list[ToolIntent]:
        return [
            i
            for i in self._intents.values()
            if i.run_id == run_id and i.status == IntentStatus.COMMITTED
        ]

    def __len__(self) -> int:
        return len(self._intents)

    # ── 持久化 ──────────────────────────────────────────────────────

    def _flush(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for intent in self._intents.values():
                fh.write(json.dumps(intent.to_dict(), ensure_ascii=False) + "\n")
        tmp.replace(self.path)

    def _load(self) -> None:
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                intent = ToolIntent.from_dict(json.loads(line))
            except (ValueError, KeyError):
                continue  # 单条损坏不阻塞恢复
            self._intents[intent.intent_id] = intent

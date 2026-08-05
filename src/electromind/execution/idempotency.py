"""Idempotency — 外部副作用的不重复执行契约（M2 §7.5）。

有副作用的操作（提交 Job、删除、覆盖写入、远程上传）必须具备
``IdempotencyKey``：

- 同一 Key 重复请求不会再次执行；已成功执行时返回原始结果。
- 执行状态未知时进入 ``RECONCILING``，绝不自动重试。
- ``sbatch`` / 删除 / 覆盖写入 / 远程上传不得盲目重试。
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from ..atomicfile import atomic_write_text, load_jsonl_recover


class IdempotencyStatus(StrEnum):
    UNKNOWN = "unknown"  # 记录已建立但结果未知（需要对账）
    COMPLETED = "completed"  # 已成功执行，结果已记录
    RECONCILING = "reconciling"  # 状态不确定，禁止自动重试


class IdempotencyKey:
    """确定性副作用键：run_id + step_id + action_id + 归一化参数摘要。"""

    def __init__(self, key: str) -> None:
        self.key = key

    @staticmethod
    def derive(
        *,
        run_id: str,
        step_id: str = "",
        action_id: str = "",
        tool_name: str = "",
        args: dict[str, Any] | None = None,
    ) -> "IdempotencyKey":
        """从语义分量派生键。归一化参数（排序 JSON）进入摘要。"""
        payload = {
            "run_id": run_id,
            "step_id": step_id,
            "action_id": action_id,
            "tool_name": tool_name,
            "args": args if args is not None else {},
        }
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        return IdempotencyKey(f"idem:{run_id}:{step_id}:{action_id}:{digest[:32]}")

    def __str__(self) -> str:
        return self.key

    def __eq__(self, other: object) -> bool:
        return isinstance(other, IdempotencyKey) and other.key == self.key

    def __hash__(self) -> int:
        return hash(self.key)


@dataclass(slots=True)
class IdempotencyRecord:
    key: str
    status: IdempotencyStatus
    result: str = ""  # 原始结果（成功时）
    created_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "status": str(self.status),
            "result": self.result,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "IdempotencyRecord":
        return cls(
            key=d["key"],
            status=IdempotencyStatus(d.get("status", "unknown")),
            result=d.get("result", ""),
            created_at=d.get("created_at", time.time()),
        )


class IdempotencyStore:
    """副作用记录存储（内存 + 可选 JSONL 持久化）。

    规则：
    - ``record_completed`` 对已 COMPLETED 的 key 返回原结果（不二次执行）。
    - ``record_unknown`` 建立 UNKNOWN 记录；重复请求不得自动重试。
    - ``record_reconciling`` 标记对账中；外部确认前保持 RECONCILING。
    - 键按 run_id 作用域隔离（不同 Run 的相同工具调用不冲突）。
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._records: dict[str, IdempotencyRecord] = {}
        self.path = Path(path) if path else None
        if self.path is not None:
            self._load()

    # ── 查询 ─────────────────────────────────────────────────────────

    def get(self, key: IdempotencyKey) -> IdempotencyRecord | None:
        return self._records.get(key.key)

    def is_duplicate(self, key: IdempotencyKey) -> bool:
        """同 key 已 COMPLETED → 重复请求（必须重放原结果）。"""
        record = self._records.get(key.key)
        return record is not None and record.status == IdempotencyStatus.COMPLETED

    def is_reconciling(self, key: IdempotencyKey) -> bool:
        record = self._records.get(key.key)
        return record is not None and record.status == IdempotencyStatus.RECONCILING

    def get_result(self, key: IdempotencyKey) -> str | None:
        record = self._records.get(key.key)
        if record is None or record.status != IdempotencyStatus.COMPLETED:
            return None
        return record.result

    # ── 写入 ─────────────────────────────────────────────────────────

    def record_completed(self, key: IdempotencyKey, result: str) -> str:
        """记录成功结果。同 key 已 COMPLETED → 返回原始结果（幂等重放）。"""
        existing = self._records.get(key.key)
        if existing is not None and existing.status == IdempotencyStatus.COMPLETED:
            return existing.result
        self._records[key.key] = IdempotencyRecord(
            key=key.key,
            status=IdempotencyStatus.COMPLETED,
            result=result,
            created_at=time.time(),
        )
        self._flush()
        return result

    def record_unknown(self, key: IdempotencyKey) -> IdempotencyRecord:
        """执行状态未知时建立/保持 UNKNOWN（不得自动重试）。"""
        self._records[key.key] = IdempotencyRecord(
            key=key.key,
            status=IdempotencyStatus.UNKNOWN,
            created_at=time.time(),
        )
        self._flush()
        return self._records[key.key]

    def record_reconciling(self, key: IdempotencyKey) -> IdempotencyRecord:
        """进入对账状态：外部确认（scheduler 查询/人工）前禁止重试。"""
        self._records[key.key] = IdempotencyRecord(
            key=key.key,
            status=IdempotencyStatus.RECONCILING,
            created_at=time.time(),
        )
        self._flush()
        return self._records[key.key]

    # ── 持久化 ──────────────────────────────────────────────────────

    def _flush(self) -> None:
        if self.path is None:
            return
        # P1.2/P1.3: 原子写 + .bak 备份（损坏恢复用）。
        atomic_write_text(
            self.path,
            "".join(
                json.dumps(r.to_dict(), ensure_ascii=False) + "\n"
                for r in self._records.values()
            ),
            encoding="utf-8",
            backup=True,
        )

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        # P1.3: 整份损坏 → 尝试 .bak；单条损坏 fail-soft 跳过。
        for d in load_jsonl_recover(self.path, parse_line=json.loads):
            try:
                record = IdempotencyRecord.from_dict(d)
            except (ValueError, KeyError):
                continue  # 单条损坏不阻塞恢复（fail-soft 读取）
            self._records[record.key] = record

    def __len__(self) -> int:
        return len(self._records)

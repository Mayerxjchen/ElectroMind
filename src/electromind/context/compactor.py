"""Compaction — 长对话摘要压缩（M3 §8.3 / §8.4）。

- 摘要不能替代原始消息存档（原始消息保留在 conversation store）。
- 摘要不能修改用户的确定性约束（固定约束消息 100% 保留原文）。
- 新信息与旧摘要冲突时必须保留冲突记录。
- 摘要更新不能静默删除未解决问题。
- 压缩后 ToolCall/ToolResult 配对保持完整。
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class SummaryRecord:
    """一段历史摘要的元数据。"""

    summary_id: str
    source_message_range: tuple[int, int]  # [start, end) 消息索引
    source_digest: str  # 原始消息内容的 SHA-256
    created_by_model: str
    created_at: float = field(default_factory=time.time)
    version: int = 1
    text: str = ""  # 摘要文本
    conflicts: tuple[str, ...] = ()  # 与旧摘要的冲突记录
    unresolved: tuple[str, ...] = ()  # 未解决问题（摘要更新不静默删除）

    def to_dict(self) -> dict:
        return {
            "summary_id": self.summary_id,
            "source_message_range": list(self.source_message_range),
            "source_digest": self.source_digest,
            "created_by_model": self.created_by_model,
            "created_at": self.created_at,
            "version": self.version,
            "text": self.text,
            "conflicts": list(self.conflicts),
            "unresolved": list(self.unresolved),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SummaryRecord":
        rng = d.get("source_message_range", [0, 0])
        return cls(
            summary_id=d["summary_id"],
            source_message_range=(int(rng[0]), int(rng[1])),
            source_digest=d.get("source_digest", ""),
            created_by_model=d.get("created_by_model", ""),
            created_at=d.get("created_at", time.time()),
            version=d.get("version", 1),
            text=d.get("text", ""),
            conflicts=tuple(d.get("conflicts", [])),
            unresolved=tuple(d.get("unresolved", [])),
        )


def digest_messages(messages: list[dict]) -> str:
    """消息列表的确定性摘要。"""
    payload = json.dumps(messages, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


class Compactor:
    """按策略压缩消息历史。

    ``keep_recent_turns``：保留的最近原始消息条数（含全部 tool 配对）。
    ``pinned_constraints``：必须原文保留的用户约束子串。
    """

    def __init__(
        self,
        *,
        keep_recent_turns: int = 6,
        pinned_constraints: tuple[str, ...] = (),
        model: str = "compactor",
        make_summary: Any = None,  # callable(text)->str；None = 截断摘要
    ) -> None:
        self.keep_recent_turns = keep_recent_turns
        self.pinned_constraints = pinned_constraints
        self.model = model
        self.make_summary = make_summary
        self.records: list[SummaryRecord] = []
        self._next_id = 1

    def _contains_constraint(self, text: str) -> bool:
        return any(c and c in text for c in self.pinned_constraints)

    def compact(self, messages: list[dict]) -> tuple[list[dict], SummaryRecord | None]:
        """压缩消息列表，返回 (新列表, 摘要记录)。

        保留：
        1. system 消息。
        2. 含固定约束的用户消息（原文 100% 保留）。
        3. 最近的 ``keep_recent_turns`` 轮（含全部 tool 配对）。
        其余轮次折叠为一条摘要 user 消息。
        """
        if not messages:
            return messages, None

        system = [m for m in messages if m.get("role") == "system"]
        pinned: list[dict] = []
        recent_start = max(0, len(messages) - self.keep_recent_turns)
        old: list[dict] = []
        for index, message in enumerate(messages):
            role = message.get("role", "")
            if role == "system":
                continue
            content = message.get("content")
            text = content if isinstance(content, str) else str(content or "")
            if self._contains_constraint(text) and role == "user":
                pinned.append(message)
            elif index >= recent_start:
                pass  # 保留在 recent 中
            else:
                old.append(message)

        if not old:
            return list(messages), None

        recent = messages[recent_start:]
        # 摘要
        old_text = "\n".join(f"{m.get('role')}: {m.get('content', '')}" for m in old)
        if self.make_summary is not None:
            summary_text = self.make_summary(old_text)
        else:
            summary_text = old_text[:1000] + ("" if len(old_text) <= 1000 else " …")
        record = SummaryRecord(
            summary_id=f"sum-{self._next_id}",
            source_message_range=(0, recent_start),
            source_digest=digest_messages(old),
            created_by_model=self.model,
            text=summary_text,
        )
        self._next_id += 1
        self.records.append(record)

        summary_message = {
            "role": "user",
            "content": (
                "[历史摘要] 以下为早期对话的摘要（原始消息已存档）：\n" + summary_text
            ),
        }
        return system + pinned + [summary_message] + recent, record

    def pairing_intact(self, messages: list[dict]) -> bool:
        """压缩后 ToolCall/ToolResult 配对完整性检查。"""
        called: set[str] = set()
        resolved: set[str] = set()
        for m in messages:
            role = m.get("role", "")
            if role == "assistant":
                for call in m.get("tool_calls") or []:
                    if isinstance(call, dict):
                        called.add(call.get("id", ""))
            elif role == "tool":
                resolved.add(m.get("tool_call_id", ""))
        return called <= resolved

    def to_dict(self) -> dict:
        return {
            "records": [r.to_dict() for r in self.records],
            "keep_recent_turns": self.keep_recent_turns,
            "pinned_constraints": list(self.pinned_constraints),
        }

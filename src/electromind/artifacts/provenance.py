"""ValueProvenance — 数值级溯源（P0-7 §11.2 验收）。

报告中的每个数值必须能追溯到：原始文件 → 文件内位置 → 解析规则 →
单位。仅记录 Artifact 级单位不够；这里为「单个数值」建立溯源记录。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ValueProvenance:
    """一个数值结论的完整溯源。"""

    value: str  # 数值原文（保留字符串精度）
    unit: str  # 单位（Hartree / eV / Å ...）
    source_file: str  # 原始文件路径
    source_line: int = 0  # 文件内行号（0 = 未知）
    source_snippet: str = ""  # 匹配片段
    parser: str = ""  # 解析规则/解析器名
    artifact_id: str = ""  # 所属 Artifact
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "unit": self.unit,
            "source_file": self.source_file,
            "source_line": self.source_line,
            "source_snippet": self.source_snippet,
            "parser": self.parser,
            "artifact_id": self.artifact_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ValueProvenance":
        return cls(
            value=d.get("value", ""),
            unit=d.get("unit", ""),
            source_file=d.get("source_file", ""),
            source_line=int(d.get("source_line", 0)),
            source_snippet=d.get("source_snippet", ""),
            parser=d.get("parser", ""),
            artifact_id=d.get("artifact_id", ""),
            created_at=d.get("created_at", time.time()),
        )


class ProvenanceStore:
    """数值溯源索引（JSONL 持久化；按 artifact/文件/单位检索）。"""

    def __init__(self, path: str | None = None) -> None:
        self._records: list[ValueProvenance] = []
        self.path = path
        if path:
            self._load()

    def record(self, provenance: ValueProvenance) -> ValueProvenance:
        self._records.append(provenance)
        self._flush()
        return provenance

    def for_artifact(self, artifact_id: str) -> list[ValueProvenance]:
        return [r for r in self._records if r.artifact_id == artifact_id]

    def for_file(self, source_file: str) -> list[ValueProvenance]:
        return [r for r in self._records if r.source_file == source_file]

    def with_unit(self, unit: str) -> list[ValueProvenance]:
        return [r for r in self._records if r.unit == unit]

    def all(self) -> list[ValueProvenance]:
        return list(self._records)

    def __len__(self) -> int:
        return len(self._records)

    def _flush(self) -> None:
        if not self.path:
            return
        from pathlib import Path

        path = Path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for record in self._records:
                fh.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        tmp.replace(path)

    def _load(self) -> None:
        from pathlib import Path

        path = Path(self.path)
        if not path.exists():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                self._records.append(ValueProvenance.from_dict(json.loads(line)))
            except (ValueError, KeyError):
                continue  # 单条损坏不阻塞恢复

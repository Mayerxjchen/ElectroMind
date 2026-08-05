"""确定性科学输出 Parser（P2，非 HPC 部分）。

只做一件事：把程序的 stdout/log 解析成结构化结论，供 Artifact
VALIDATED / REJECTED 判定使用。绝不修改 Artifact 状态本身——
状态推进由 RunEngine 完成（``artifact_validate`` / ``reject_validation``）。

约定：
- 每个 parser 返回一个 :class:`ParseResult`（或子类），字段固定，
  下游（VALDIATED 门、Timeline/Inspector、DeePMD 训练门）只读这些字段。
- Scheduler COMPLETED ≠ 科学成功：即使作业退出码为 0，只要 parser 判定
  terminated/valid 不成立，Artifact 就不进入 VALIDATED。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class ParseOutcome(StrEnum):
    VALID = "valid"  # 程序正常结束 + 关键数值齐全 → 可 VALIDATED
    NOT_CONVERGED = "not_converged"  # 程序结束但 SCF/迭代未收敛
    FAILED = "failed"  # 明确失败（OOM / TIMEOUT / ABORT / 崩溃）
    TRUNCATED = "truncated"  # 输出被截断（无正常结束标志）
    UNKNOWN = "unknown"  # 无法判定（空输出 / 不可识别）


@dataclass(slots=True)
class ParseResult:
    """Parser 的结构化结论。所有字段均有默认值，解析失败不抛错。"""

    outcome: ParseOutcome = ParseOutcome.UNKNOWN
    parser: str = ""
    summary: str = ""  # 人类可读一句话结论
    energy: float | None = None
    energy_unit: str = ""  # Hartree / eV / ...
    scf_converged: bool | None = None
    scf_iterations: int | None = None
    forces: list[dict[str, Any]] = field(
        default_factory=list
    )  # {atom, fx, fy, fz, |F|}
    force_unit: str = ""
    md_steps: int = 0
    terminated_cleanly: bool = False
    truncated: bool = False
    details: dict[str, Any] = field(default_factory=dict)  # 扩展字段
    warnings: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        """是否足以支撑 Artifact 进入 VALIDATED。"""
        return (
            self.outcome is ParseOutcome.VALID
            and self.terminated_cleanly
            and not self.truncated
            and self.energy is not None
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": str(self.outcome),
            "parser": self.parser,
            "summary": self.summary,
            "energy": self.energy,
            "energy_unit": self.energy_unit,
            "scf_converged": self.scf_converged,
            "scf_iterations": self.scf_iterations,
            "forces": self.forces,
            "force_unit": self.force_unit,
            "md_steps": self.md_steps,
            "terminated_cleanly": self.terminated_cleanly,
            "truncated": self.truncated,
            "details": self.details,
            "warnings": self.warnings,
            "valid": self.valid,
        }


def parse_file(path: str | Path, *, parser: str) -> ParseResult:
    """读取文件并调用对应 parser；文件不可读返回 UNKNOWN（不抛错）。"""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        result = ParseResult(outcome=ParseOutcome.UNKNOWN, parser=parser)
        result.summary = f"无法读取文件: {p}"
        result.warnings.append("file_unreadable")
        return result
    if not text.strip():
        result = ParseResult(outcome=ParseOutcome.UNKNOWN, parser=parser)
        result.summary = "输出为空，无法判定"
        result.warnings.append("empty_output")
        return result
    from . import cp2k

    impl = {
        "cp2k": cp2k.parse_cp2k_output,
    }.get(parser)
    if impl is None:
        result = ParseResult(outcome=ParseOutcome.UNKNOWN, parser=parser)
        result.summary = f"未知 parser: {parser}"
        result.warnings.append("unknown_parser")
        return result
    result = impl(text)
    result.parser = parser
    return result

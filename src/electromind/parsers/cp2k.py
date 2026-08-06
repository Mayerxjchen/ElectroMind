"""CP2K 输出确定性 Parser（P2.2）。

识别的关键信号（基于 CP2K 8.x/2024.x 标准输出格式）：

终止信号
- 正常：``PROGRAM ENDED IN CP2K`` / ``PROGRAM ENDED AT <时间戳>``
  （CP2K 版本不同结束标志不同：8.x 及更早为 IN CP2K，2023+ 为 AT；
  两者都算正常完成的权威标志）
- 异常：``PROGRAM ABORTED``、``ABORTING``、``DEADLINE EXCEEDED``、
  ``*** OOM ***``、``out of memory``、``Killed``、``Traceback``、
  ``segmentation fault``

SCF 收敛
- ``SCF run converged in <N> steps`` → 收敛
- ``SCF run NOT converged`` → 未收敛
- 逐行 ``... OT ... <iter> <...>  <E> <dE>`` 记录迭代

能量
- ``ENERGY| Total FORCE_EVAL ( QS ) energy [Hartree]  <value>``
  （单位可为 Hartree 或 a.u.，等价）

力
- ``ATOMIC FORCES in [a.u.]`` 后的表格：``Atom  Kind  Element  x  y  z``

MD 步数
- ``MD| Step number: <N>``

截断
- 有内容但既无 ``PROGRAM ENDED IN CP2K`` 也无明确异常标志 → 输出被截断
  （作业被杀 / 写盘中断 / 还在跑）。绝不猜测为成功。

单位约定：CP2K 总能量单位是 Hartree（a.u.）；力单位是 a.u./bohr。
"""

from __future__ import annotations

import re

from . import ParseOutcome, ParseResult

# 兼容旧版（PROGRAM ENDED IN CP2K）与 2023+ 新版（PROGRAM ENDED AT <ts>）
_PROGRAM_ENDED = re.compile(r"PROGRAM ENDED (?:IN CP2K|AT)")
_ABORT_SIGNALS = re.compile(
    r"PROGRAM ABORTED|ABORTING|DEADLINE EXCEEDED|\*\*\* OOM \*\*\*|"
    r"out of memory|Killed|Traceback|segmentation fault|fatal error",
    re.IGNORECASE,
)
_SCF_CONVERGED = re.compile(r"SCF run converged in\s+(\d+)\s+steps", re.IGNORECASE)
_SCF_NOT_CONVERGED = re.compile(r"SCF run NOT converged", re.IGNORECASE)
# ENERGY| Total FORCE_EVAL ( QS ) energy [Hartree]       -76.4031729171
_ENERGY_LINE = re.compile(
    r"ENERGY\|\s*Total FORCE_EVAL\b.*\benergy\s*\[\s*([A-Za-z.\s]+?)\s*\]\s*([-\d.]+(?:[Ee][+-]?\d+)?)"
)
# 力表表头： Atom  Kind  Element  x  y  z
_FORCE_HEADER = re.compile(r"^\s*Atom\s+Kind\s+Element\s+x\s+y\s+z\s*$")
# 力表行：      1      1  C       -2.34   1.01   0.00
_FORCE_ROW = re.compile(
    r"^\s*\d+\s+\d+\s+[A-Za-z]{1,2}\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s*$"
)
_MD_STEP = re.compile(r"MD\|\s*Step number:\s+(\d+)")


def parse_cp2k_output(text: str) -> ParseResult:
    result = ParseResult()
    lines = text.splitlines()

    ended = bool(_PROGRAM_ENDED.search(text))
    aborted = bool(_ABORT_SIGNALS.search(text))

    # ── SCF 收敛 ───────────────────────────────────────────────────
    scf_conv = _SCF_CONVERGED.search(text)
    scf_not = _SCF_NOT_CONVERGED.search(text)
    if scf_conv:
        result.scf_converged = True
        result.scf_iterations = int(scf_conv.group(1))
    elif scf_not:
        result.scf_converged = False
    else:
        result.scf_converged = None

    # ── 能量（取最后一行，迭代结束后的总能量）────────────────────
    for line in lines:
        m = _ENERGY_LINE.search(line)
        if m:
            unit = m.group(1).strip()
            result.energy = float(m.group(2))
            result.energy_unit = (
                "Hartree" if unit.lower() in ("hartree", "a.u.", "au") else unit
            )

    # ── 力 ────────────────────────────────────────────────────────
    in_forces = False
    force_unit = ""
    for line in lines:
        if line.strip().startswith("ATOMIC FORCES"):
            in_forces = True
            unit_m = re.search(r"\[([^\]]+)\]", line)
            if unit_m:
                force_unit = unit_m.group(1)
            continue
        if in_forces and _FORCE_HEADER.match(line):
            continue
        if in_forces and _FORCE_ROW.match(line):
            fx, fy, fz = (float(v) for v in _FORCE_ROW.match(line).groups())
            result.forces.append(
                {
                    "fx": fx,
                    "fy": fy,
                    "fz": fz,
                    "magnitude": (fx**2 + fy**2 + fz**2) ** 0.5,
                }
            )
        elif (
            in_forces
            and line.strip()
            and not line.strip().startswith(
                ("SUM OF ATOMIC FORCES", "MAXIMUM FORCE", "AVERAGE FORCE", "SUM", "-")
            )
        ):
            # 离开力表区域
            if _FORCE_ROW.match(line) is None and not _FORCE_HEADER.match(line):
                in_forces = False
    if force_unit:
        result.force_unit = force_unit

    # ── MD 步数 ────────────────────────────────────────────────────
    md_steps = [int(m.group(1)) for m in _MD_STEP.finditer(text)]
    result.md_steps = max(md_steps) if md_steps else 0

    # ── 判定 ───────────────────────────────────────────────────────
    result.terminated_cleanly = ended and not aborted
    result.truncated = (not ended and not aborted) and bool(text.strip())
    result.details = {"lines": len(lines)}

    if aborted:
        result.outcome = ParseOutcome.FAILED
        if re.search(r"DEADLINE EXCEEDED|TIMEOUT|time limit", text, re.I):
            result.summary = "CP2K 超时（DEADLINE EXCEEDED / TIMEOUT）"
            result.warnings.append("timeout")
        elif re.search(r"OOM|out of memory|memory alloc", text, re.I):
            result.summary = "CP2K 内存不足（OOM）"
            result.warnings.append("oom")
        elif re.search(r"killed", text, re.I):
            result.summary = "CP2K 被系统终止（Killed）"
            result.warnings.append("killed")
        else:
            result.summary = "CP2K 异常终止（ABORT / 崩溃）"
            result.warnings.append("aborted")
    elif result.truncated:
        result.outcome = ParseOutcome.TRUNCATED
        result.summary = "CP2K 输出被截断，未出现正常结束标志"
        result.warnings.append("truncated")
    elif ended:
        if result.scf_converged is False:
            result.outcome = ParseOutcome.NOT_CONVERGED
            result.summary = "CP2K 正常结束但 SCF 未收敛"
            result.warnings.append("scf_not_converged")
        elif result.energy is None:
            # 程序结束但没抓到总能量 → 不能算科学成功
            result.outcome = ParseOutcome.FAILED
            result.summary = "CP2K 正常结束但未解析到总能量"
            result.warnings.append("energy_missing")
        else:
            result.outcome = ParseOutcome.VALID
            result.summary = (
                f"CP2K 正常结束；总能量 {result.energy:.6f} {result.energy_unit}"
                + (
                    f"，SCF {result.scf_iterations} 步收敛"
                    if result.scf_iterations
                    else ""
                )
            )
    else:
        result.outcome = ParseOutcome.UNKNOWN
        result.summary = "CP2K 输出无法判定（无结束标志也无异常标志）"
        result.warnings.append("unknown")

    return result

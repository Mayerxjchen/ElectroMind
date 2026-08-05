"""确定性验证器 — 检查工具序列、Artifact、状态与约束。

所有断言只依赖确定性的可观察状态（消息历史、文件系统、工具调用记录），
不依赖模型文本输出。每个失败归类到 M0 §5.3 的七个类别之一。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from .task import (
    ExpectedOutcome,
    FailureCategory,
    TaskSpec,
)


@dataclass(slots=True)
class EvalObservation:
    """一次任务运行的可观察状态。"""

    thread_dir: Path
    workdir: Path
    # (tool_name, arguments_dict) 实际工具调用序列
    tool_calls: list[tuple[str, dict]] = field(default_factory=list)
    # 按调用顺序的完整结果：{"name", "args", "ok", "content"}
    call_results: list[dict] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)  # 最终消息历史（role/content）
    stop_reason: str = ""
    run_phase: str = ""
    side_effect_log: list[str] = field(default_factory=list)  # 外部副作用记录
    error: str = ""  # 运行异常（模拟中断等），非空表示 failed

    def tool_names(self) -> list[str]:
        return [name for name, _ in self.tool_calls]

    def message_text(self) -> str:
        return "\n".join(str(m.get("content", "")) for m in self.messages)


@dataclass(frozen=True, slots=True)
class VerificationResult:
    passed: bool
    failure: FailureCategory | None = None
    details: str = ""


class DeterministicVerifier:
    """对观察结果执行确定性验证。"""

    def verify(self, task: TaskSpec, obs: EvalObservation) -> VerificationResult:
        exp = task.expected
        for check in (
            self._check_state,
            self._check_tools,
            self._check_forbidden,
            self._check_failed_calls,
            self._check_call_results,
            self._check_artifacts,
            self._check_constraints,
            self._check_command,
        ):
            result = check(exp, obs)
            if not result.passed:
                return result
        return VerificationResult(passed=True)

    # ── 检查项 ─────────────────────────────────────────────────────

    @staticmethod
    def _check_state(exp: ExpectedOutcome, obs: EvalObservation) -> VerificationResult:
        st = exp.state
        if (
            st.terminal == "completed"
            and obs.run_phase
            not in (
                "completed",
                "ended",
                "",
            )
            and not obs.error
        ):
            return VerificationResult(
                False,
                FailureCategory.STATE,
                f"终态不是 completed: {obs.run_phase!r}",
            )
        if st.terminal == "cancelled" and obs.stop_reason != "cancelled":
            return VerificationResult(
                False,
                FailureCategory.STATE,
                f"终态不是 cancelled: stop_reason={obs.stop_reason!r} "
                f"phase={obs.run_phase!r}",
            )
        if st.terminal == "failed" and not obs.error and obs.run_phase != "failed":
            return VerificationResult(
                False, FailureCategory.STATE, f"终态不是 failed: {obs.run_phase!r}"
            )
        if st.stop_reason and obs.stop_reason != st.stop_reason:
            return VerificationResult(
                False,
                FailureCategory.STATE,
                f"stop_reason={obs.stop_reason!r} ≠ 期望 {st.stop_reason!r}",
            )
        if st.phase and obs.run_phase != st.phase:
            return VerificationResult(
                False,
                FailureCategory.STATE,
                f"run_phase={obs.run_phase!r} ≠ 期望 {st.phase!r}",
            )
        if st.no_orphan_tool_results:
            orphans = _find_orphan_tool_results(obs.messages)
            if orphans:
                return VerificationResult(
                    False,
                    FailureCategory.STATE,
                    f"存在孤立 ToolCall 无对应 ToolResult: {orphans}",
                )
        return VerificationResult(True)

    @staticmethod
    def _check_tools(exp: ExpectedOutcome, obs: EvalObservation) -> VerificationResult:
        actual = obs.tool_names()
        for expected_call in exp.tools:
            if expected_call.name not in actual:
                return VerificationResult(
                    False,
                    FailureCategory.TOOL,
                    f"期望工具 {expected_call.name!r} 未被调用；实际: {actual}",
                )
            if expected_call.args is not None:
                call = next(
                    (a for n, a in obs.tool_calls if n == expected_call.name),
                    {},
                )
                if not _args_match(expected_call.args, call):
                    return VerificationResult(
                        False,
                        FailureCategory.TOOL,
                        f"工具 {expected_call.name!r} 参数不匹配: "
                        f"期望 {expected_call.args}，实际 {call}",
                    )
        # 顺序校验：期望名称必须是实际序列的子序列（确定性脚本任务 = 精确顺序）
        expected_order = [t.name for t in exp.tools]
        if expected_order and not _is_subsequence(expected_order, actual):
            return VerificationResult(
                False,
                FailureCategory.TOOL,
                f"工具调用顺序不符：期望子序列 {expected_order}，实际 {actual}",
            )
        return VerificationResult(True)

    @staticmethod
    def _check_failed_calls(
        exp: ExpectedOutcome, obs: EvalObservation
    ) -> VerificationResult:
        for index in exp.failed_calls:
            if index >= len(obs.call_results):
                return VerificationResult(
                    False,
                    FailureCategory.SAFETY,
                    f"第 {index} 次调用未发生（共 {len(obs.call_results)} 次）",
                )
            result = obs.call_results[index]
            if result["ok"]:
                return VerificationResult(
                    False,
                    FailureCategory.SAFETY,
                    f"第 {index} 次调用应当失败但成功了: "
                    f"{result['name']}({result['args']})",
                )
        return VerificationResult(True)

    @staticmethod
    def _check_call_results(
        exp: ExpectedOutcome, obs: EvalObservation
    ) -> VerificationResult:
        for check in exp.call_results:
            index = check["index"]
            if index >= len(obs.call_results):
                return VerificationResult(
                    False,
                    FailureCategory.TOOL,
                    f"call_results 检查越界: index {index}",
                )
            result = obs.call_results[index]
            content = str(result.get("content", ""))
            if check.get("contains") and check["contains"] not in content:
                return VerificationResult(
                    False,
                    FailureCategory.VALIDATION,
                    f"第 {index} 次调用结果缺少 {check['contains']!r}: {content[:200]}",
                )
            if check.get("not_contains") and check["not_contains"] in content:
                return VerificationResult(
                    False,
                    FailureCategory.SAFETY,
                    f"第 {index} 次调用结果泄露禁止内容 "
                    f"{check['not_contains']!r}: {content[:200]}",
                )
        return VerificationResult(True)

    @staticmethod
    def _check_forbidden(
        exp: ExpectedOutcome, obs: EvalObservation
    ) -> VerificationResult:
        """禁止工具 = 不得有任何成功执行（被拒绝的尝试是安全行为）。"""
        for result in obs.call_results:
            if result["name"] in exp.forbidden_tools and result["ok"]:
                return VerificationResult(
                    False,
                    FailureCategory.SAFETY,
                    f"禁止工具 {result['name']!r} 成功执行: {result['args']}",
                )
        return VerificationResult(True)

    @staticmethod
    def _check_artifacts(
        exp: ExpectedOutcome, obs: EvalObservation
    ) -> VerificationResult:
        for art in exp.artifacts:
            path = _safe_join(obs.workdir, art.path)
            if not path.exists():
                return VerificationResult(
                    False,
                    FailureCategory.VALIDATION,
                    f"期望 Artifact 不存在: {art.path}",
                )
            text = path.read_text(encoding="utf-8", errors="replace")
            for needle in art.contains:
                if needle not in text:
                    return VerificationResult(
                        False,
                        FailureCategory.VALIDATION,
                        f"Artifact {art.path} 缺少内容片段 {needle!r}",
                    )
            for needle in art.must_not_contain:
                if needle in text:
                    return VerificationResult(
                        False,
                        FailureCategory.VALIDATION,
                        f"Artifact {art.path} 含禁止片段 {needle!r}",
                    )
        return VerificationResult(True)

    @staticmethod
    def _check_constraints(
        exp: ExpectedOutcome, obs: EvalObservation
    ) -> VerificationResult:
        text = obs.message_text()
        for constraint in exp.constraints:
            if constraint not in text:
                return VerificationResult(
                    False,
                    FailureCategory.STATE,
                    f"用户约束 {constraint!r} 在消息历史中丢失",
                )
        return VerificationResult(True)

    @staticmethod
    def _check_command(
        exp: ExpectedOutcome, obs: EvalObservation
    ) -> VerificationResult:
        if not exp.verification_command:
            return VerificationResult(True)
        import subprocess

        try:
            proc = subprocess.run(
                exp.verification_command,
                shell=True,
                cwd=obs.workdir,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            return VerificationResult(
                False,
                FailureCategory.ENVIRONMENT,
                "verification_command 超时",
            )
        if proc.returncode != 0:
            return VerificationResult(
                False,
                FailureCategory.VALIDATION,
                f"verification_command 退出码 {proc.returncode}: {proc.stderr[:500]}",
            )
        return VerificationResult(True)


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _is_subsequence(needle: list[str], haystack: list[str]) -> bool:
    """needle 必须是 haystack 的子序列（按序出现）。"""
    it = iter(haystack)
    return all(any(n == item for item in it) for n in needle)


def _safe_join(root: Path, rel: str) -> Path:
    """拒绝路径逃逸（eval 的 Artifact 检查不允许 ../ 引用工作目录外）。"""
    p = (root / rel).resolve()
    if not p.is_relative_to(root.resolve()):
        raise ValueError(f"Artifact 路径逃逸: {rel!r}")
    return p


def _args_match(expected: dict, actual: dict) -> bool:
    """归一化参数匹配：期望的每个键都等于实际的对应键。"""
    for key, value in expected.items():
        if key not in actual:
            return False
        if isinstance(value, dict):
            if not _args_match(value, actual[key]):
                return False
        elif isinstance(value, list):
            if list(actual[key]) != list(value):
                return False
        elif str(actual[key]) != str(value):
            return False
    return True


def _find_orphan_tool_results(messages: list[dict]) -> list[str]:
    """返回缺少对应 ToolResult 的 ToolCall id（tool 消息的 id 侧不配对）。"""
    called: set[str] = set()
    resolved: set[str] = set()
    for m in messages:
        role = m.get("role", "")
        if role == "assistant":
            tc = m.get("tool_calls") or []
            for call in tc:
                if isinstance(call, dict):
                    called.add(call.get("id", ""))
        elif role == "tool":
            resolved.add(m.get("tool_call_id", ""))
    return sorted(called - resolved)


def sha256_file(path: Path) -> str:
    """Artifact 的 SHA-256（Manifest 用）。"""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def side_effect_digest(obs: EvalObservation) -> str:
    """外部副作用记录的确定性摘要（用于 runs_required>1 的重复检查）。"""
    payload = json.dumps(obs.side_effect_log, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()

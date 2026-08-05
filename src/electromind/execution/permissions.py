"""Permissions — 风险分级审批（M4 §9.3 / §9.4）。

策略等级：``deny / ask / allow_once / allow_for_run / allow_for_workspace``。

Approval 必须绑定：thread / run / tool_call / action / target / workdir /
risk / expires_at —— 不可跨 Thread、跨 Run、跨参数或过期重放。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum

from ..harness.state import SessionMode


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PermissionDecision(StrEnum):
    DENY = "deny"
    ASK = "ask"
    ALLOW_ONCE = "allow_once"
    ALLOW_FOR_RUN = "allow_for_run"
    ALLOW_FOR_WORKSPACE = "allow_for_workspace"


@dataclass(frozen=True, slots=True)
class ActionSpec:
    """审批对象是具体 Action（不是只有 Tool Name）。"""

    tool: str
    command: str = ""  # EXECUTE 时的命令
    target: str = ""  # 目标路径/资源
    workdir: str = ""
    paths: tuple[str, ...] = ()
    network_hosts: tuple[str, ...] = ()
    estimated_cost: float = 0.0
    external_side_effect: bool = False
    risk: RiskLevel = RiskLevel.MEDIUM


@dataclass(frozen=True, slots=True)
class ApprovalScope:
    """Approval 的强绑定上下文；``validate`` 全不满足即拒绝。"""

    approval_id: str
    thread_id: str
    run_id: str
    tool_call_id: str
    action: ActionSpec
    expires_at: float  # epoch 秒

    def is_expired(self, *, now: float | None = None) -> bool:
        current = time.time() if now is None else now
        return current > self.expires_at

    def validate(
        self,
        *,
        thread_id: str,
        run_id: str,
        tool_call_id: str,
        action: ActionSpec | None = None,
        now: float | None = None,
    ) -> str | None:
        """返回拒绝原因；None = 绑定全部吻合且未过期。"""
        if thread_id != self.thread_id:
            return "approval 属于其他 Thread"
        if run_id != self.run_id:
            return "approval 属于其他 Run"
        if tool_call_id != self.tool_call_id:
            return "approval 绑定其他 ToolCall"
        if action is not None and action != self.action:
            return "action 参数变化，必须重新审批"
        if self.is_expired(now=now):
            return "approval 已过期"
        return None


class RiskPolicy:
    """按模式与配置产生审批决策。

    模式语义（SessionMode）：
    - ``ask``：只读；WRITE/EXECUTE 一律 ask，HIGH/CRITICAL deny。
    - ``plan``：可 propose 文件改动但不应用；写类 ask。
    - ``run``：低/中风险按配置放行，高/严重必须 ask/deny。
    """

    def __init__(
        self,
        mode: SessionMode = SessionMode.RUN,
        *,
        auto_approve: bool = False,
        allow_network: bool = False,
        allow_file_write: bool = False,
        allow_execute: bool = False,
        max_approval_wait_seconds: int = 300,
    ) -> None:
        self.mode = mode
        self.auto_approve = auto_approve
        self.allow_network = allow_network
        self.allow_file_write = allow_file_write
        self.allow_execute = allow_execute
        self.max_approval_wait_seconds = max_approval_wait_seconds

    def decide(self, action: ActionSpec) -> PermissionDecision:
        """对具体 Action 的决策。严重风险默认不能自动批准。"""
        risk = action.risk

        if risk == RiskLevel.CRITICAL:
            return (
                PermissionDecision.DENY
                if self.mode == SessionMode.ASK
                else PermissionDecision.ASK
            )

        if self.mode == SessionMode.ASK:
            if risk == RiskLevel.LOW:
                return PermissionDecision.ALLOW_FOR_RUN
            return PermissionDecision.DENY

        if self.mode == SessionMode.PLAN:
            if risk in (RiskLevel.LOW,):
                return PermissionDecision.ALLOW_FOR_RUN
            return PermissionDecision.ASK

        # RUN 模式
        if risk == RiskLevel.LOW:
            return PermissionDecision.ALLOW_FOR_RUN
        if risk == RiskLevel.MEDIUM:
            if action.tool == "run_command":
                if not self.allow_execute:
                    return PermissionDecision.ASK
                return PermissionDecision.ALLOW_FOR_RUN
            if self._auto_allows(action):
                return PermissionDecision.ALLOW_FOR_RUN
            return PermissionDecision.ASK
        # HIGH
        return PermissionDecision.ASK

    def _auto_allows(self, action: ActionSpec) -> bool:
        if action.external_side_effect:
            return False  # 外部副作用永不自动（先于 auto_approve）
        if self.auto_approve:
            return True
        if action.tool == "write_file" and self.allow_file_write:
            return True
        if action.tool == "fetch_url" and self.allow_network:
            return True
        if action.tool == "web_search" and self.allow_network:
            return True
        return False


# ── 静态风险表（Action → RiskLevel；M4 §9.4 推荐分类） ─────────────────


def risk_of_action(action: ActionSpec) -> RiskLevel:
    """按 Action 内容计算风险（工具名 + 目标 + 命令）。"""
    tool = action.tool
    if tool in ("read_file", "list_dir", "list_host_files"):
        return RiskLevel.LOW
    if tool in ("web_search", "fetch_url"):
        return RiskLevel.MEDIUM
    if tool in ("write_file", "str_replace", "copy_from_host"):
        return RiskLevel.MEDIUM
    if tool == "run_command":
        command = (action.command or "").strip()
        if _is_destructive_command(command):
            return RiskLevel.CRITICAL
        return RiskLevel.HIGH
    if tool == "copy_to_host":
        return RiskLevel.HIGH
    if tool == "submit_external" or action.external_side_effect:
        return RiskLevel.HIGH
    if tool in ("delete_file", "rm") or action.risk == RiskLevel.CRITICAL:
        return RiskLevel.CRITICAL
    return action.risk


_DESTRUCTIVE_PREFIXES = (
    "rm -rf",
    "rm -fr",
    "mkfs",
    "dd if=",
    "shutdown",
    "reboot",
    ":(){",
)


def _is_destructive_command(command: str) -> bool:
    lowered = command.lower()
    return any(lowered.startswith(p) for p in _DESTRUCTIVE_PREFIXES)

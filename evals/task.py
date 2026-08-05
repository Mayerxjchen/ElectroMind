"""ElectroMind Agent Eval 框架 — Golden Task 定义。

任务声明格式（M0 验收 §5.2）：

```yaml
id:           唯一任务 ID
category:     planning | tool_use | safety | context | scientific | recovery
input:        固定用户输入
title:        人类可读标题
description:  任务说明
provider:     脚本化模型步骤（确定性）
expected:     确定性验证声明
```

模型输出允许文本差异，但状态、工具、副作用和 Artifact 必须可确定验证。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

# ---------------------------------------------------------------------------
# 失败分类（M0 §5.3）
# ---------------------------------------------------------------------------


class FailureCategory(StrEnum):
    PLANNING = "planning"
    MODEL = "model"
    TOOL = "tool"
    ENVIRONMENT = "environment"
    STATE = "state"
    VALIDATION = "validation"
    SAFETY = "safety"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# 任务声明
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExpectedToolCall:
    """期望出现的工具调用（按序）。args 为归一化参数匹配。"""

    name: str
    args: dict[str, Any] | None = None  # None 表示只匹配名称


@dataclass(frozen=True, slots=True)
class ExpectedArtifact:
    """期望产出的文件系统 Artifact。"""

    path: str  # 相对工作目录
    contains: tuple[str, ...] = ()  # 必须包含的文本片段
    must_not_contain: tuple[str, ...] = ()  # 不得包含的文本片段


@dataclass(frozen=True, slots=True)
class ExpectedState:
    """期望的终态断言（可为空）。"""

    stop_reason: str | None = None  # no_tool_calls | max_turns | cancelled | ...
    terminal: str | None = "completed"  # completed | cancelled | failed
    phase: str | None = None  # 精确 RunPhase 字符串
    no_orphan_tool_results: bool = False  # 不允许孤立 ToolCall


@dataclass(frozen=True, slots=True)
class ExpectedOutcome:
    """确定性验证声明集合。"""

    tools: tuple[ExpectedToolCall, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    artifacts: tuple[ExpectedArtifact, ...] = ()
    state: ExpectedState = field(default_factory=ExpectedState)
    constraints: tuple[str, ...] = ()  # 必须保留在消息历史中的约束文本
    verification_command: str = ""  # 工作目录内执行的确定性检查命令（exit 0 通过）
    risk_level: RiskLevel = RiskLevel.LOW
    timeout_seconds: int = 30
    runs_required: int = 1  # 连续执行次数（>1 用于副作用确定性检查）
    # 按调用位置（0 基）要求结果失败（safety：未授权/逃逸被拒绝）
    failed_calls: tuple[int, ...] = ()
    # 按调用位置检查结果内容: {"index": int, "contains": str?, "not_contains": str?}
    call_results: tuple[dict, ...] = ()


@dataclass(frozen=True, slots=True)
class ProviderStep:
    """脚本化模型步骤。"""

    type: str  # "text" | "tools"
    content: str = ""
    reasoning: str = ""  # text 步骤可附带思考内容
    calls: tuple[dict[str, Any], ...] = ()  # tools 步骤的工具调用（name/arguments）

    @classmethod
    def text(cls, content: str) -> "ProviderStep":
        return cls(type="text", content=content)

    @classmethod
    def tools(cls, *calls: dict[str, Any]) -> "ProviderStep":
        return cls(type="tools", calls=calls)


@dataclass(frozen=True, slots=True)
class TaskSpec:
    """Golden Task 声明。"""

    id: str
    category: str
    input: str
    title: str = ""
    description: str = ""
    provider: tuple[ProviderStep, ...] = ()
    expected: ExpectedOutcome = field(default_factory=ExpectedOutcome)
    system: str = "你是严格的确定性助手。"  # 额外 system 提示
    max_turns: int = 12
    fixtures: tuple[dict[str, str], ...] = ()  # (relpath → content)，运行前写入工作目录
    tools: tuple[str, ...] = ()  # 额外注入工具名（safety/recovery 专用）
    # engine 类任务（不跑 agent 循环）用 driver 闭包，定义在 tasks 注册表里
    driver: str = ""  # 注册的 driver 名（planning 类任务用）
    cancel_after_events: int = 0  # >0：第 N 个事件后注入取消（recovery 取消测试）
    declares_provider: bool = False  # JSON 中显式声明了 provider 键（可为空列表）

    @classmethod
    def from_dict(cls, d: dict) -> "TaskSpec":
        declares_provider = "provider" in d
        provider = tuple(
            ProviderStep(
                type=s["type"],
                content=s.get("content", ""),
                reasoning=s.get("reasoning", ""),
                calls=tuple(s.get("calls", ())),
            )
            for s in d.get("provider", [])
        )
        exp = d.get("expected", {})
        state = exp.get("state", {})
        return cls(
            id=d["id"],
            category=d["category"],
            input=d["input"],
            title=d.get("title", ""),
            description=d.get("description", ""),
            provider=provider,
            expected=ExpectedOutcome(
                tools=tuple(
                    ExpectedToolCall(name=t["name"], args=t.get("args"))
                    for t in exp.get("tools", [])
                ),
                forbidden_tools=tuple(exp.get("forbidden_tools", [])),
                artifacts=tuple(
                    ExpectedArtifact(
                        path=a["path"],
                        contains=tuple(a.get("contains", [])),
                        must_not_contain=tuple(a.get("must_not_contain", [])),
                    )
                    for a in exp.get("artifacts", [])
                ),
                state=ExpectedState(
                    stop_reason=state.get("stop_reason"),
                    terminal=state.get("terminal", "completed"),
                    phase=state.get("phase"),
                    no_orphan_tool_results=state.get("no_orphan_tool_results", False),
                ),
                constraints=tuple(exp.get("constraints", [])),
                verification_command=exp.get("verification_command", ""),
                risk_level=RiskLevel(exp.get("risk_level", "low")),
                timeout_seconds=exp.get("timeout_seconds", 30),
                runs_required=exp.get("runs_required", 1),
                failed_calls=tuple(exp.get("failed_calls", [])),
                call_results=tuple(exp.get("call_results", [])),
            ),
            system=d.get("system", "你是严格的确定性助手。"),
            max_turns=d.get("max_turns", 12),
            fixtures=tuple((f["path"], f["content"]) for f in d.get("fixtures", [])),
            tools=tuple(d.get("tools", [])),
            driver=d.get("driver", ""),
            declares_provider=declares_provider,
            cancel_after_events=int(d.get("cancel_after_events", 0)),
        )

    def validate(self) -> list[str]:
        """返回声明校验错误列表（空 = 合法）。"""
        errors: list[str] = []
        if not self.id:
            errors.append("id 为空")
        valid_categories = {
            "planning",
            "tool_use",
            "safety",
            "context",
            "scientific",
            "recovery",
        }
        if self.category not in valid_categories:
            errors.append(f"非法 category: {self.category!r}")
        if not self.input:
            errors.append("input 为空")
        if self.driver:
            if self.provider:
                errors.append("driver 任务不能同时声明 provider")
        else:
            if not self.declares_provider:
                errors.append("agent 任务必须声明 provider 键")
        if self.expected.runs_required < 1:
            errors.append("runs_required 必须 ≥1")
        if (
            self.expected.state.no_orphan_tool_results
            and not self.expected.state.stop_reason
        ):
            errors.append("no_orphan_tool_results 需要声明 stop_reason")
        return errors

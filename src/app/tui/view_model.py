"""语义视图模型：RenderItem 联合类型 + CliViewModel + 状态行 + Composer。

Reducer 产出 RenderItem；Renderer 只消费 CliViewModel。禁止从事件直接拼 ANSI。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# RenderItem（不可变快照；文本型条目支持流式追加）
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class UserMessageItem:
    kind: str = "user_message"
    id: str = ""
    text: str = ""
    delivery: str = (
        ""  # accepted | applied | queued | deferred | rejected（input/state 回填）
    )


@dataclass(slots=True)
class AssistantMessageItem:
    kind: str = "assistant_message"
    id: str = ""
    text: str = ""
    done: bool = False


@dataclass(slots=True)
class ActivityItem:
    """公开活动（如“正在检查 4 个输入文件”）；不是 raw reasoning。"""

    kind: str = "activity"
    id: str = ""
    text: str = ""
    running: bool = True
    done: bool = False


@dataclass(slots=True)
class ToolItem:
    kind: str = "tool"
    id: str = ""  # tool_call_id
    name: str = ""
    args_summary: str = ""
    target: str = ""  # sandbox | local | ssh
    workdir: str = ""
    status: str = "running"  # running | ok | failed
    exit_code: int | None = None
    duration_s: float | None = None
    output_lines: int = 0
    output_preview: str = ""
    full_output: str = ""  # 不常驻主视图；Overlay 按需取


@dataclass(slots=True)
class ApprovalItem:
    kind: str = "approval"
    id: str = ""  # approval-<tool_call_id>
    approval_id: str = ""  # harness ApprovalRequest 标识（解析用）
    tool_call_id: str = ""
    name: str = ""
    command: str = ""
    target: str = ""
    workdir: str = ""
    risk: str = ""
    status: str = "pending"  # pending | approved | denied | expired


@dataclass(slots=True)
class ErrorItem:
    kind: str = "error"
    id: str = ""
    message: str = ""


@dataclass(slots=True)
class RunStatusItem:
    kind: str = "run_status"
    id: str = ""
    text: str = ""


@dataclass(slots=True)
class SystemNoticeItem:
    kind: str = "system_notice"
    id: str = ""
    text: str = ""


RenderItem = (
    UserMessageItem
    | AssistantMessageItem
    | ActivityItem
    | ToolItem
    | ApprovalItem
    | ErrorItem
    | RunStatusItem
    | SystemNoticeItem
)


# ---------------------------------------------------------------------------
# 状态行 / Composer / 视图模型
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class StatusLineState:
    run_status: str = (
        "idle"  # idle | generating | running_tool | approval | cancelling | completed
    )
    mode: str = "run"
    target: str = "sandbox"
    permission: str = "prompt"
    model: str = ""
    project: str = ""
    context_pct: int | None = None

    def segments(self) -> list[str]:
        """窄终端按优先级隐藏：mode → target → run_status → permission → model → project → context。"""
        ordered = [
            ("mode", self.mode.upper()),
            ("target", self.target),
            ("run_status", self.run_status),
            ("permission", self.permission),
            ("model", self.model),
            ("project", self.project),
            (
                "context",
                f"ctx {self.context_pct}%" if self.context_pct is not None else None,
            ),
        ]
        return [text for _, text in ordered if text]


@dataclass(slots=True)
class ComposerState:
    prompt_prefix: str = "Run> "  # 按模式：Ask> / Plan> / Run>
    delivery: str = ""  # sending | accepted | applied | queued | deferred | rejected
    active_run: bool = False
    approval_pending: bool = False


@dataclass(slots=True)
class ScrollState:
    offset: int = 0  # 0 = 跟随底部；>0 向上滚动行数
    pinned: bool = False


@dataclass(slots=True)
class CliViewModel:
    thread_id: str = ""
    run_id: str = ""
    items: list[RenderItem] = field(default_factory=list)
    composer: ComposerState = field(default_factory=ComposerState)
    status: StatusLineState = field(default_factory=StatusLineState)
    overlay: object | None = None
    scroll: ScrollState = field(default_factory=ScrollState)

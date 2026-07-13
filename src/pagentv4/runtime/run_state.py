from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..core.events import StopReason

RunPhase = Literal[
    "idle",
    "initializing",
    "waking_sandbox",
    "running",
    "generating",
    "calling",
    "tearing_down",
    "closing",
    "ended",
]

RUN_PHASE_LABELS: dict[RunPhase, str] = {
    "idle": "空闲",
    "initializing": "正在初始化",
    "waking_sandbox": "正在唤醒沙箱",
    "running": "运行中",
    "generating": "正在生成",
    "calling": "正在函数调用",
    "tearing_down": "正在销毁",
    "closing": "正在关闭",
    "ended": "已结束",
}


@dataclass
class RunState:
    """Runner 当前 run / 生命周期的轻量状态。"""

    phase: RunPhase = "idle"
    turn_id: int = 0
    turn: int = 0
    stop_reason: StopReason | None = None

    @property
    def label(self) -> str:
        return RUN_PHASE_LABELS[self.phase]

    @property
    def active(self) -> bool:
        return self.phase in (
            "initializing",
            "waking_sandbox",
            "running",
            "generating",
            "calling",
            "tearing_down",
            "closing",
        )

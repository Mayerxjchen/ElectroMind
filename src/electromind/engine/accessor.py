"""进程级引擎访问器（G1b）。

工具在 Runner 构造时装配，而 RunEngine 由 App 层（wire / CLI client）
进程级共享创建——工具拿不到引擎引用。App 层启动时调用
``set_engine(engine)`` 注册，模型工具（plan/artifact 桥）经
``get_engine()`` 取当前引擎（线程内唯一：CLI REPL / wire 各自单引擎）。

未注册时调用方应视为"引擎不可用"（工具返回失败消息，不崩溃）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .run_engine import RunEngine

_engine: "RunEngine | None" = None


def set_engine(engine: "RunEngine") -> None:
    """注册进程级引擎（重复注册以后者为准；传 None 清空）。"""
    global _engine
    _engine = engine


def get_engine() -> "RunEngine | None":
    """取当前引擎；未注册返回 None（调用方自行处理）。"""
    return _engine

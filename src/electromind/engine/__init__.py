"""Engine — 唯一执行内核（M1）。

- ``run_engine``：RunEngine，Run 生命周期的唯一实现（状态/控制面/事件）。
- 目标架构：``CLI / Wire / HTTP → Application Service → RunEngine``；
  ``harness`` 逐步并入本模块语义。
"""

from .run_engine import RunEngine, RunEngineError

__all__ = ["RunEngine", "RunEngineError"]

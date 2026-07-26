"""Resource / ResourceSlot —— 帧栈上的资源生命周期与归属。

一次运行会占用两类有生命周期的资源：sandbox（进程 / 容器 / SSH 会话）和
conversation store（文件句柄 / SQLite 连接）。子 agent 委派时它们既可能被复用，
也可能各起一份，弹帧时只能关掉"这一帧自己开的"，不能误关父帧还在用的。

这里把生命周期收敛成一个维度——``close``：

- `Resource`：能被关闭的资源。Sandbox 天然满足（自带 async ``close``）；
  ConversationStore 的 ``close`` 是可选同步方法，用 `ConversationResource` 对齐。
- `ResourceSlot`：把一份资源和"当前帧是否拥有它"绑在一起。归属是帧与资源之间的
  关系，不是资源自身的属性——同一个 sandbox 对开它的父帧是 owned、对借用它的子帧
  是 borrowed。弹帧时遍历槽位，只 `close` 掉 ``owned=True`` 的。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..conversation import ConversationStore


@runtime_checkable
class Resource(Protocol):
    """有 open/close 生命周期、可在帧间共享的资源。

    帧栈只依赖 ``close`` 这一个能力：弹帧时关掉本帧拥有的资源。open 由帧构造器
    （`assemble_run_resources`）按各资源自己的方式完成，不放进协议里强求统一。
    """

    async def close(self) -> None: ...


class ConversationResource:
    """把 ConversationStore 包成统一的 `Resource`。

    store 的 ``close`` 是可选的同步方法（Jsonl 后端没有，SQLite 后端有），这里把它
    对齐成 async ``close``，让帧栈面对所有资源都用同一个 ``await resource.close()``。
    """

    def __init__(self, store: ConversationStore) -> None:
        self.store = store

    async def close(self) -> None:
        close = getattr(self.store, "close", None)
        if callable(close):
            close()


@dataclass
class ResourceSlot:
    """一份资源 + 当前帧对它的归属。

    ``owned=True`` 表示这份资源由本帧开出，弹帧时负责关闭；``owned=False`` 表示借用
    自父帧，弹帧时放手不关。
    """

    resource: Resource
    owned: bool

    async def release(self) -> None:
        if self.owned:
            await self.resource.close()

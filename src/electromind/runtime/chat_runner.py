"""ChatRunner —— 只打开 conversation 能力的 BaseRunner 子类。

不需要 sandbox、skills，但仍然先打开 thread，再使用 thread 里的 conversation。

配置来源优先级：代码参数 > 配置文件 > 默认值。

用法::

    # 最简：全部默认
    r = ChatRunner(agent)
    async for text in r.run("hello", return_type="text"):
        print(text)
    await r.close()

    # 指定 thread_id 和 thread 根目录
    r = ChatRunner(agent, thread_id="weather-demo", root=".electromind/threads/")

    # 从配置文件
    r = ChatRunner.from_toml("chat.toml", agent)
"""

from __future__ import annotations

import tomllib
from datetime import datetime
from pathlib import Path

from ..core.agent import Agent
from ..core.message import Messages
from ..ithread import ThreadSpec
from .base_runner import BaseRunner
from .thread import Thread


class ChatRunner(BaseRunner):
    """只打开 conversation，不开 sandbox。

    配置来源（优先级从高到低）：

    1. 代码参数（root / thread_id / backend 等）
    2. 配置文件（TOML，通过 from_toml 加载）
    3. 默认值（.electromind/threads/ + 自动生成 thread_id）
    """

    def __init__(
        self,
        agent: Agent,
        *,
        thread_id: str | None = None,
        conversation_id: str | None = None,
        root: str | Path | None = None,
        conversation_root: str = ".",
        backend: str = "jsonl",
        messages: Messages | None = None,
        spec: ThreadSpec | None = None,
    ):
        resolved_thread_id = (
            thread_id
            or conversation_id
            or datetime.now().strftime("thread-%Y%m%d-%H%M%S")
        )
        resolved_spec = spec or ThreadSpec(
            conversation_backend=backend,
            conversation_root=conversation_root,
            backend="none",  # ChatRunner 不开 sandbox
        )
        thread = Thread.open(
            resolved_thread_id, root=root, overrides=resolved_spec.__dict__
        )

        super().__init__(agent, thread, messages=messages)

    @classmethod
    def from_toml(
        cls,
        path: str | Path,
        agent: Agent,
        *,
        thread_id: str | None = None,
        root: str | Path | None = None,
        messages: Messages | None = None,
    ) -> ChatRunner:
        """从 TOML 配置文件创建 ChatRunner。

        配置文件格式同 ThreadSpec 的 [conversation] section：

            [conversation]
            backend = "jsonl"
            root = "."
            messages_id = "my-chat"
        """
        with Path(path).open("rb") as fp:
            payload = tomllib.load(fp)
        spec = ThreadSpec.from_dict(payload)
        spec.backend = "none"  # ChatRunner 不开 sandbox

        return cls(
            agent,
            thread_id=thread_id,
            root=root,
            messages=messages,
            spec=spec,
        )

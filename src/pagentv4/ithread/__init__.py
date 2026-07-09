"""IThread —— Thread 层的最小能力协议 + ThreadSpec 声明式配置。

这个包只定义"Thread 长什么样"：字段、配置结构、对上暴露的能力。
具体实现（本地磁盘、远端存储等）在 runtime/ 里提供。

# IThread 与 ThreadSpec

`IThread` 是对上暴露的 Protocol，`Runner` 只依赖它。
`ThreadSpec` 是与 `thread.toml` 一一对应的声明式配置对象。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..conversation import ConversationStore
from ..core.message import Messages
from ..sandbox import Sandbox

THREAD_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$")
SPEC_FILENAME = "thread.toml"
WORKSPACE_DIRNAME = "workspace"
MESSAGES_CONVERSATION_ID = "messages"


def validate_thread_id(thread_id: str) -> None:
    if THREAD_ID_PATTERN.match(thread_id):
        return
    raise ValueError(
        f"invalid thread_id: {thread_id!r}; "
        "must match [A-Za-z0-9][A-Za-z0-9_.-]{0,127}"
    )


@dataclass
class ThreadSpec:
    """一个 thread 的长期配置；首次冻结、写进 thread.toml。"""

    conversation_backend: str = "jsonl"
    conversation_root: str = "."
    conversation_db_path: str = "conversations.sqlite"
    conversation_messages_id: str = MESSAGES_CONVERSATION_ID

    backend: str = "local"
    image: str | None = None
    container_ttl_seconds: int | None = None
    ssh_host: str | None = None
    ssh_config: str = "~/.ssh/config"
    ssh_workdir: str = "~/agent"
    command_policy: str = "workdir"
    model: str = "deepseek-v4-flash"
    system: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "conversation": {
                "backend": self.conversation_backend,
                "root": self.conversation_root,
                "db_path": self.conversation_db_path,
                "messages_id": self.conversation_messages_id,
            },
            "sandbox": {
                "backend": self.backend,
                "image": self.image,
                "container_ttl_seconds": self.container_ttl_seconds,
                "command_policy": self.command_policy,
            },
            "ssh": {
                "host": self.ssh_host,
                "config": self.ssh_config,
                "workdir": self.ssh_workdir,
            },
            "agent": {
                "model": self.model,
                "system": self.system,
            },
            "extra": dict(self.extra),
        }

    @classmethod
    def from_dict(cls, payload: dict) -> ThreadSpec:
        conversation = payload.get("conversation", {})
        sandbox = payload.get("sandbox", {})
        ssh = payload.get("ssh", {})
        agent = payload.get("agent", {})

        known = {
            "conversation_backend": conversation.get(
                "backend", payload.get("conversation_backend", "jsonl")
            ),
            "conversation_root": conversation.get(
                "root", payload.get("conversation_root", ".")
            ),
            "conversation_db_path": conversation.get(
                "db_path", payload.get("conversation_db_path", "conversations.sqlite")
            ),
            "conversation_messages_id": conversation.get(
                "messages_id",
                payload.get("conversation_messages_id", MESSAGES_CONVERSATION_ID),
            ),
            "backend": sandbox.get("backend", payload.get("backend", "local")),
            "image": sandbox.get("image", payload.get("image")),
            "container_ttl_seconds": sandbox.get(
                "container_ttl_seconds", payload.get("container_ttl_seconds")
            ),
            "command_policy": sandbox.get(
                "command_policy", payload.get("command_policy", "workdir")
            ),
            "ssh_host": ssh.get("host", payload.get("ssh_host")),
            "ssh_config": ssh.get("config", payload.get("ssh_config", "~/.ssh/config")),
            "ssh_workdir": ssh.get("workdir", payload.get("ssh_workdir", "~/agent")),
            "model": agent.get("model", payload.get("model", "deepseek-v4-flash")),
            "system": agent.get("system", payload.get("system", "")),
        }

        extra = dict(payload.get("extra", {}))
        known_sections = {"conversation", "sandbox", "ssh", "agent", "extra"}
        for name, value in payload.items():
            if name in known_sections or name in cls.field_names():
                continue
            extra[name] = value
        for name, value in conversation.items():
            if name not in {"backend", "root", "db_path", "messages_id"}:
                extra[f"conversation.{name}"] = value
        for name, value in sandbox.items():
            if name not in {
                "backend",
                "image",
                "container_ttl_seconds",
                "command_policy",
            }:
                extra[f"sandbox.{name}"] = value
        for name, value in ssh.items():
            if name not in {"host", "config", "workdir"}:
                extra[f"ssh.{name}"] = value
        for name, value in agent.items():
            if name not in {"model", "system"}:
                extra[f"agent.{name}"] = value
        if extra:
            known["extra"] = extra
        return cls(**known)

    @classmethod
    def field_names(cls) -> set[str]:
        return {f.name for f in cls.__dataclass_fields__.values()}


@runtime_checkable
class IThread(Protocol):
    """Thread 层对上暴露的最小能力；`Runner` 只依赖这个协议。"""

    id: str
    root: Path
    spec_path: Path
    spec: ThreadSpec
    created: bool
    ignored_overrides: tuple[str, ...]

    @property
    def workspace_path(self) -> Path: ...

    @property
    def messages_conversation_id(self) -> str: ...

    def open_store(self) -> ConversationStore: ...

    def load_messages(self) -> Messages: ...

    async def open_sandbox(self) -> Sandbox: ...

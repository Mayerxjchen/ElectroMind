"""IThread —— Thread 层的最小能力协议 + ThreadSpec 声明式配置。

这个包只定义"Thread 长什么样"：字段、配置结构、对上暴露的能力。
具体实现（本地磁盘、远端存储等）在 runtime/ 里提供。

# IThread 与 ThreadSpec

`IThread` 是对上暴露的 Protocol，`Runner` 只依赖它。
`ThreadSpec` 是与 `thread.toml` 一一对应的声明式配置对象。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..conversation import ConversationStore
from ..core.message import Messages
from ..sandbox import Sandbox

THREAD_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$")
SPEC_FILENAME = "thread.toml"
METAINFO_FILENAME = "metainfo.json"
WORKSPACE_DIRNAME = "workspace"
MESSAGES_CONVERSATION_ID = "messages"


def validate_thread_id(thread_id: str) -> None:
    if THREAD_ID_PATTERN.match(thread_id):
        return
    raise ValueError(
        f"invalid thread_id: {thread_id!r}; "
        "must match [A-Za-z0-9][A-Za-z0-9_.-]{0,127}"
    )


def toml_field(section: str, key: str, default):
    """声明一个绑定到 thread.toml `[section] key` 的 ThreadSpec 字段。

    section / key 存进 dataclass metadata，`to_dict` / `from_dict` 据此推导映射，
    新增字段只需在此声明一行，两个方向自动生效。

    Args:
        section: TOML section 名（conversation / sandbox / ssh / agent）。
        key: 该 section 下的键名（可与字段名不同，如 ssh_host -> [ssh] host）。
        default: 字段默认值，须为不可变类型。
    """
    return field(default=default, metadata={"section": section, "key": key})


@dataclass
class ThreadSpec:
    """一个 thread 的长期配置；首次冻结、写进 thread.toml。

    字段扁平铺开（`spec.backend` / `spec.image` 等），消费方直接按属性读取；
    到 TOML 的分组由每个字段的 `toml_field(section, key)` metadata 决定。
    """

    conversation_backend: str = toml_field("conversation", "backend", "jsonl")
    conversation_root: str = toml_field("conversation", "root", ".")
    conversation_db_path: str = toml_field(
        "conversation", "db_path", "conversations.sqlite"
    )
    conversation_messages_id: str = toml_field(
        "conversation", "messages_id", MESSAGES_CONVERSATION_ID
    )

    backend: str = toml_field("sandbox", "backend", "local")
    image: str | None = toml_field("sandbox", "image", None)
    container_ttl_seconds: int | None = toml_field(
        "sandbox", "container_ttl_seconds", None
    )
    command_policy: str = toml_field("sandbox", "command_policy", "workdir")

    ssh_host: str | None = toml_field("ssh", "host", None)
    ssh_config: str = toml_field("ssh", "config", "~/.ssh/config")
    ssh_workdir: str = toml_field("ssh", "workdir", "~/agent")

    model: str = toml_field("agent", "model", "deepseek-v4-flash")
    system: str = toml_field("agent", "system", "")

    extra: dict = field(default_factory=dict)

    @classmethod
    def section_bindings(cls) -> list[tuple[str, str, str]]:
        """返回 (field_name, section, key) 列表；仅含绑定到 TOML section 的字段。"""
        return [
            (f.name, f.metadata["section"], f.metadata["key"])
            for f in fields(cls)
            if "section" in f.metadata
        ]

    def to_dict(self) -> dict:
        sections: dict[str, dict] = {}
        for name, section, key in self.section_bindings():
            sections.setdefault(section, {})[key] = getattr(self, name)
        sections["extra"] = dict(self.extra)
        return sections

    @classmethod
    def from_dict(cls, payload: dict) -> ThreadSpec:
        known: dict = {}
        for name, section, key in cls.section_bindings():
            block = payload.get(section, {})
            if key in block:
                known[name] = block[key]
            elif name in payload:  # 兼容顶层扁平写法（旧格式）
                known[name] = payload[name]

        section_keys: dict[str, set[str]] = {}
        for _, section, key in cls.section_bindings():
            section_keys.setdefault(section, set()).add(key)

        extra = dict(payload.get("extra", {}))
        top_level_skip = set(section_keys) | {"extra"} | cls.field_names()
        for name, value in payload.items():
            if name not in top_level_skip:
                extra[name] = value
        for section, keys in section_keys.items():
            block = payload.get(section, {})
            if not isinstance(block, dict):
                continue
            for name, value in block.items():
                if name not in keys:
                    extra[f"{section}.{name}"] = value
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
    def metainfo_path(self) -> Path: ...

    def load_metainfo(self) -> dict: ...

    def save_metainfo(self, metainfo: dict) -> None: ...

    @property
    def messages_conversation_id(self) -> str: ...

    def open_store(self) -> ConversationStore: ...

    def load_messages(self) -> Messages: ...

    async def open_sandbox(self) -> Sandbox: ...

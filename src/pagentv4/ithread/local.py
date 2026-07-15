"""Thread 具体实现：本地磁盘上的 thread 目录 + TOML 配置 + sandbox。

目录布局：

    <cwd>/.pagent/threads/<thread_id>/
        thread.toml        # thread 配置（首次冻结）
        metainfo.json      # 面向用户的元信息（标题、时间戳、对话摘要）
        workspace/         # 沙箱工作目录

thread_id 是内部管理编号（thread-<时间戳>），metainfo.json 里的 title 才是面向
用户展示的名字，前端列会话时优先显示它。

抽象定义（IThread、ThreadSpec）在同包的 __init__ 里。
"""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from ..conversation import JsonlConversationStore, SqliteConversationStore
from ..core.message import Messages
from ..sandbox import Sandbox, open_sandbox_for_spec
from . import (
    METAINFO_FILENAME,
    SPEC_FILENAME,
    WORKSPACE_DIRNAME,
    ThreadSpec,
    validate_thread_id,
)


def load_thread_toml(path: Path) -> dict:
    with path.open("rb") as fp:
        return tomllib.load(fp)


def format_toml_value(value: str | int | bool) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def dump_thread_toml(payload: dict) -> str:
    lines: list[str] = []
    for section, values in payload.items():
        if not isinstance(values, dict):
            continue
        items = [(name, value) for name, value in values.items() if value is not None]
        if not items:
            continue
        lines.append(f"[{section}]")
        for name, value in items:
            if isinstance(value, dict):
                continue
            lines.append(f"{name} = {format_toml_value(value)}")
        lines.append("")
    if lines:
        lines.pop()
    return "\n".join(lines) + "\n"


def default_threads_root() -> Path:
    """`<cwd>/.pagent/threads/`；要自定义就给 `Thread.open(root=...)`。"""
    return Path(os.getcwd()) / ".pagent" / "threads"


@dataclass
class Thread:
    """一个 thread 的长期上下文 handle；落到本地磁盘的 `IThread` 实现。"""

    id: str
    root: Path
    spec_path: Path
    spec: ThreadSpec
    created: bool
    ignored_overrides: tuple[str, ...] = ()

    @property
    def workspace_path(self) -> Path:
        return self.root / WORKSPACE_DIRNAME

    @property
    def metainfo_path(self) -> Path:
        return self.root / METAINFO_FILENAME

    def load_metainfo(self) -> dict:
        """读面向用户的元信息（标题、时间戳、摘要）；文件不存在返回空 dict。"""
        if not self.metainfo_path.exists():
            return {}
        with self.metainfo_path.open("r", encoding="utf-8") as fp:
            return json.load(fp)

    def save_metainfo(self, metainfo: dict) -> None:
        """写面向用户的元信息到 metainfo.json（覆盖式，缩进便于人读）。"""
        self.metainfo_path.write_text(
            json.dumps(metainfo, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @property
    def messages_conversation_id(self) -> str:
        return self.spec.conversation_messages_id

    @property
    def conversation_root_path(self) -> Path:
        path = Path(os.path.expanduser(self.spec.conversation_root))
        if path.is_absolute():
            return path
        return self.root / path

    @property
    def conversation_db_path(self) -> Path:
        path = Path(os.path.expanduser(self.spec.conversation_db_path))
        if path.is_absolute():
            return path
        return self.root / path

    @property
    def messages_storage_path(self) -> Path:
        if self.spec.conversation_backend == "jsonl":
            store = JsonlConversationStore(root=self.conversation_root_path)
            return store.path_for(self.messages_conversation_id)
        return self.conversation_db_path

    def open_store(self) -> JsonlConversationStore | SqliteConversationStore:
        if self.spec.conversation_backend == "jsonl":
            return JsonlConversationStore(root=self.conversation_root_path)
        if self.spec.conversation_backend == "sqlite":
            return SqliteConversationStore(db_path=self.conversation_db_path)
        raise ValueError(
            f"thread {self.id!r}: unknown conversation backend "
            f"{self.spec.conversation_backend!r}"
        )

    def load_messages(self) -> Messages:
        if (
            self.spec.conversation_backend == "sqlite"
            and not self.conversation_db_path.exists()
        ):
            return Messages()
        store = self.open_store()
        messages = store.load(self.messages_conversation_id)
        close = getattr(store, "close", None)
        if callable(close):
            close()
        return messages

    async def open_sandbox(self) -> Sandbox:
        return await open_sandbox_for_spec(
            self.spec,
            str(self.workspace_path),
            label=f"thread {self.id!r}",
        )

    @classmethod
    def open(
        cls,
        thread_id: str,
        *,
        root: Path | str | None = None,
        overrides: dict | None = None,
    ) -> Thread:
        """打开或首次创建一个 thread。

        - 目录不存在：把 `overrides`（缺省 {}）合进 ThreadSpec 默认值写入 thread.toml，
          mkdir workspace/。
        - 目录已存在：读 thread.toml；`overrides` 里跟已存字段冲突的项被忽略，
          实际使用的 spec 仍以磁盘为准。`ignored_overrides` 记录哪些字段被丢了。
        """
        validate_thread_id(thread_id)
        base = Path(root) if root is not None else default_threads_root()
        thread_dir = base / thread_id
        spec_path = thread_dir / SPEC_FILENAME
        provided = dict(overrides or {})

        if spec_path.exists():
            payload = load_thread_toml(spec_path)
            existing = ThreadSpec.from_dict(payload)
            ignored = cls.diff_overrides(existing, provided)
            thread_dir.mkdir(parents=True, exist_ok=True)
            (thread_dir / WORKSPACE_DIRNAME).mkdir(parents=True, exist_ok=True)
            return cls(
                id=thread_id,
                root=thread_dir,
                spec_path=spec_path,
                spec=existing,
                created=False,
                ignored_overrides=tuple(ignored),
            )

        spec = ThreadSpec(**provided) if provided else ThreadSpec()
        thread_dir.mkdir(parents=True, exist_ok=True)
        (thread_dir / WORKSPACE_DIRNAME).mkdir(parents=True, exist_ok=True)
        spec_path.write_text(
            dump_thread_toml(spec.to_dict()),
            encoding="utf-8",
        )
        return cls(
            id=thread_id, root=thread_dir, spec_path=spec_path, spec=spec, created=True
        )

    @staticmethod
    def diff_overrides(existing: ThreadSpec, overrides: dict) -> list[str]:
        ignored: list[str] = []
        for name, value in overrides.items():
            if name not in ThreadSpec.field_names() or name == "extra":
                continue
            if value != getattr(existing, name):
                ignored.append(name)
        return ignored

"""Thread 具体实现：本地磁盘上的 thread 目录 + TOML 配置 + sandbox。

目录布局：

    ~/.pagent/threads/<thread_id>/
        thread.toml          # thread 配置（首次冻结；可含 [project] path、[sub.<name>]）
        metainfo.json        # 面向用户的元信息（标题、时间戳、对话摘要、usage 快照）
        workspaces/
            main/            # 主 agent 沙箱地盘
            <sub_name>/      # 子 agent（delegate）各自的沙箱地盘（按需新建）
        messages/
            messages.jsonl   # 主对话
            messages.sub.<name>.<seq>.jsonl  # 子对话（delegate 产生），同 thread 落盘

``[project].path`` 是用户侧工作目录：挂到 sandbox 的 host_root（list_host_files /
copy_from_host / copy_to_host → ``<project>/artifacts``），不是沙箱 workdir。

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
from ..paths import default_pagent_home
from ..sandbox import Sandbox, open_sandbox_for_spec
from . import (
    MAIN_WORKSPACE_NAME,
    METAINFO_FILENAME,
    SPEC_FILENAME,
    SUB_SECTION,
    WORKSPACES_DIRNAME,
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


def format_toml_array(values: tuple | list) -> str:
    items = ", ".join(format_toml_value(item) for item in values)
    return f"[{items}]"


def format_toml_kv_lines(values: dict) -> list[str]:
    """把一个 TOML 表的键值对渲染成行；跳过 None、空数组、嵌套 dict。"""
    lines: list[str] = []
    for name, value in values.items():
        if value is None or isinstance(value, dict):
            continue
        if isinstance(value, (tuple, list)):
            if not value:
                continue
            lines.append(f"{name} = {format_toml_array(value)}")
            continue
        lines.append(f"{name} = {format_toml_value(value)}")
    return lines


def dump_thread_toml(payload: dict) -> str:
    blocks: list[list[str]] = []
    for section, values in payload.items():
        if not isinstance(values, dict) or not values:
            continue
        if section == SUB_SECTION:
            # sub 是 name -> spec 的嵌套表，渲染成 [sub.<name>] 子表。
            for name, spec in values.items():
                if not isinstance(spec, dict):
                    continue
                kv = format_toml_kv_lines(spec)
                if kv:
                    blocks.append([f"[{SUB_SECTION}.{name}]", *kv])
            continue
        kv = format_toml_kv_lines(values)
        if kv:
            blocks.append([f"[{section}]", *kv])
    body = "\n\n".join("\n".join(block) for block in blocks)
    return body + "\n" if body else "\n"


def default_threads_root() -> Path:
    """``~/.pagent/threads/``；要自定义就给 `Thread.open(root=...)`。"""
    return default_pagent_home() / "threads"


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
        """主 agent 沙箱地盘：``workspaces/main/``，与用户 project 分离。"""
        return self.workspace_path_for(MAIN_WORKSPACE_NAME)

    def workspace_path_for(self, name: str) -> Path:
        """按名字取沙箱地盘 ``workspaces/<name>/``；主 agent 用 ``main``，
        子 agent（delegate）各自命名，同一 thread 下互不干扰。"""
        return self.root / WORKSPACES_DIRNAME / name

    @property
    def project_path(self) -> Path | None:
        """用户侧工作目录（host_root）；未绑定则 None。"""
        if not self.spec.project_path:
            return None
        return Path(os.path.expanduser(self.spec.project_path)).resolve()

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

    async def open_sandbox(self, name: str = MAIN_WORKSPACE_NAME) -> Sandbox:
        """打开某个命名 workspace 的沙箱；主 agent 用 ``main``，子 agent 各自命名。"""
        workspace = self.workspace_path_for(name)
        workspace.mkdir(parents=True, exist_ok=True)
        label = (
            f"thread {self.id!r}"
            if name == MAIN_WORKSPACE_NAME
            else (f"thread {self.id!r} sub {name!r}")
        )
        return await open_sandbox_for_spec(
            self.spec,
            str(workspace),
            label=label,
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
          mkdir workspaces/main/。
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
            # resume 时补写迟到的自描述字段：老 thread.toml 没有 [lock] 段，或
            # project_path 首次绑定，都在这里回填一次并落盘（唯一事实来源随之补全）。
            backfilled = False
            if existing.project_path is None and isinstance(
                provided.get("project_path"), str
            ):
                existing.project_path = provided["project_path"]
                provided.pop("project_path")
                backfilled = True
            if not existing.file_self_fs_pos:
                existing.file_self_fs_pos = str(spec_path.resolve())
                backfilled = True
            if backfilled:
                spec_path.write_text(
                    dump_thread_toml(existing.to_dict()),
                    encoding="utf-8",
                )
            ignored = cls.diff_overrides(existing, provided)
            thread_dir.mkdir(parents=True, exist_ok=True)
            (thread_dir / WORKSPACES_DIRNAME / MAIN_WORKSPACE_NAME).mkdir(
                parents=True, exist_ok=True
            )
            return cls(
                id=thread_id,
                root=thread_dir,
                spec_path=spec_path,
                spec=existing,
                created=False,
                ignored_overrides=tuple(ignored),
            )

        spec = ThreadSpec(**provided) if provided else ThreadSpec()
        # 冻结时把 thread.toml 自身的绝对路径写进 [lock]（自指锚点，单一事实来源）。
        spec.file_self_fs_pos = str(spec_path.resolve())
        thread_dir.mkdir(parents=True, exist_ok=True)
        (thread_dir / WORKSPACES_DIRNAME / MAIN_WORKSPACE_NAME).mkdir(
            parents=True, exist_ok=True
        )
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
            current = getattr(existing, name)
            # TOML 数组回读成 list，覆盖项常是 tuple；同序列内容不算冲突。
            if isinstance(value, (tuple, list)) and isinstance(current, (tuple, list)):
                if list(value) != list(current):
                    ignored.append(name)
                continue
            if value != current:
                ignored.append(name)
        return ignored

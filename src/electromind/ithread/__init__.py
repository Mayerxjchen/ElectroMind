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
WORKSPACES_DIRNAME = "workspaces"
MAIN_WORKSPACE_NAME = "main"
MESSAGES_DIRNAME = "messages"
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


SUB_SECTION = "sub"

# thread.toml 结构版本；随 spec 落盘到 [lock] schema_version，供后续迁移识别。
THREAD_SCHEMA_VERSION = 1


@dataclass
class SubAgentSpec:
    """一个命名子 agent 的配置；对应 thread.toml 里的 ``[sub.<name>]``。

    子 agent 由主 agent 通过 delegate 工具启动，跑在同一 thread、同一 Runner 上。
    这些字段决定子 agent 起来时用什么 model、要不要自己的沙箱与 workspace：

    - ``system``：子 agent 的系统提示词。
    - ``model``：模型；空表示继承主 agent 的 model。
    - ``backend``：沙箱后端；空表示继承 thread 的 backend，``"none"`` 表示不开沙箱。
    - ``sandbox_tools``：沙箱工具白名单；空表示放开全部。
    - ``max_turns``：子 agent 的循环上限。
    - ``workspace``：独立 workspace 名；空表示复用主 agent 的 ``main`` workspace，
      非空则在 ``workspaces/<name>/`` 下开自己的地盘。
    - ``max_depth``：委派深度上限（默认 1；系统最大 2）。
    - ``max_tokens``：总 token 预算（0 = 不限制）。
    - ``max_tool_calls``：工具调用次数上限（0 = 不限制）。
    - ``timeout_seconds``：子 agent 运行超时（0 = 不限制）。
    - ``allowed_tools``：工具白名单；空表示放开全部。
    - ``read_paths`` / ``write_paths``：读写路径边界；空表示不限制。
    """

    system: str = ""
    model: str = ""
    backend: str = ""
    sandbox_tools: tuple[str, ...] = ()
    max_turns: int = 24
    workspace: str = ""
    # M5 委派预算
    max_depth: int = 1
    max_tokens: int = 0
    max_tool_calls: int = 0
    timeout_seconds: float = 0.0
    allowed_tools: tuple[str, ...] = ()
    read_paths: tuple[str, ...] = ()
    write_paths: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        data: dict = {
            "system": self.system,
            "model": self.model,
            "backend": self.backend,
            "sandbox_tools": list(self.sandbox_tools),
            "max_turns": self.max_turns,
            "workspace": self.workspace,
            "max_depth": self.max_depth,
            "max_tokens": self.max_tokens,
            "max_tool_calls": self.max_tool_calls,
            "timeout_seconds": self.timeout_seconds,
            "allowed_tools": list(self.allowed_tools),
            "read_paths": list(self.read_paths),
            "write_paths": list(self.write_paths),
        }
        return {
            key: value for key, value in data.items() if value not in ("", [], 0, 0.0)
        }

    @classmethod
    def from_dict(cls, payload: dict) -> SubAgentSpec:
        tools = payload.get("sandbox_tools", ())
        return cls(
            system=payload.get("system", ""),
            model=payload.get("model", ""),
            backend=payload.get("backend", ""),
            sandbox_tools=tuple(tools),
            max_turns=payload.get("max_turns", 24),
            workspace=payload.get("workspace", ""),
            max_depth=payload.get("max_depth", 1),
            max_tokens=payload.get("max_tokens", 0),
            max_tool_calls=payload.get("max_tool_calls", 0),
            timeout_seconds=payload.get("timeout_seconds", 0.0),
            allowed_tools=tuple(payload.get("allowed_tools", ())),
            read_paths=tuple(payload.get("read_paths", ())),
            write_paths=tuple(payload.get("write_paths", ())),
        )


@dataclass
class ThreadSpec:
    """一个 thread 的长期配置；首次冻结、写进 thread.toml。

    字段扁平铺开（`spec.backend` / `spec.image` 等），消费方直接按属性读取；
    到 TOML 的分组由每个字段的 `toml_field(section, key)` metadata 决定。
    """

    # ── session mode & autonomy (replaces implicit command_policy guessing) ──
    session_mode: str = toml_field("agent", "session_mode", "agent")
    autonomy: str = toml_field("agent", "autonomy", "prompt")

    conversation_backend: str = toml_field("conversation", "backend", "jsonl")
    conversation_root: str = toml_field("conversation", "root", MESSAGES_DIRNAME)
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
    # 沙箱工具白名单：空表示放开全部（向后兼容）；非空则只启用列出的工具。
    sandbox_tools: tuple[str, ...] = toml_field("sandbox", "tools", ())

    project_path: str | None = toml_field("project", "path", None)

    ssh_host: str | None = toml_field("ssh", "host", None)
    ssh_config: str = toml_field("ssh", "config", "~/.ssh/config")
    ssh_workdir: str = toml_field("ssh", "workdir", "~/.electromind")
    # Explicit remote context files ([[ssh.context_files]] array of tables).
    # Only these exact paths are fetched; no remote scanning occurs.
    ssh_context_files: tuple[str, ...] = ()

    model: str = toml_field("agent", "model", "deepseek-v4-flash")
    system: str = toml_field("agent", "system", "")
    # 主 agent 的进程内（harness）工具白名单：thread.toml 里 [agent] tools 列了哪些，
    # 主 agent 就挂哪些。识别的名字：web_search / fetch_url / delegate_to_subagent。
    # 这是唯一事实来源——不列就没有，不再从别处静默挂载。列了 delegate_to_subagent
    # 还需配 [sub.*] 才真正启用委派。空表示不挂任何 harness 工具。
    agent_tools: tuple[str, ...] = toml_field("agent", "tools", ())
    # skill 搜索目录白名单：作为额外的 skill 搜索根目录，拼在项目/用户自动发现之后。
    # 保留作为 legacy 兼容入口；新项目建议使用标准的 skills/、.agents/skills/ 或
    # .electromind/skills/ 目录让 skills 自动被发现。
    skills: tuple[str, ...] = toml_field("agent", "skills", ())

    # [lock]：thread.toml 冻结时写入的自描述信息，首次创建落盘。
    # - schema_version：本 thread.toml 的结构版本，供后续迁移识别。
    # - file_self_fs_pos：thread.toml 自身的绝对路径，创建时注入（自指锚点）。
    schema_version: int = toml_field("lock", "schema_version", THREAD_SCHEMA_VERSION)
    file_self_fs_pos: str = toml_field("lock", "file_self_fs_pos", "")

    # 命名子 agent：name -> SubAgentSpec，对应 thread.toml 里的 [sub.<name>] 表。
    # 不走 toml_field（那套只表达单层 [section] key），由 to_dict/from_dict 专门处理。
    subs: dict[str, SubAgentSpec] = field(default_factory=dict)

    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        # subs 可能由 asdict(spec) 之类的路径传进来（值是普通 dict），统一收敛成
        # SubAgentSpec，让下游只面对一种类型。
        self.subs = {
            name: sub if isinstance(sub, SubAgentSpec) else SubAgentSpec.from_dict(sub)
            for name, sub in self.subs.items()
        }

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
        if self.subs:
            sections[SUB_SECTION] = {
                name: sub.to_dict() for name, sub in self.subs.items()
            }
        sections["extra"] = dict(self.extra)
        # Serialize [[ssh.context_files]] array of tables
        if self.ssh_context_files:
            ssh_block = sections.setdefault("ssh", {})
            ssh_block["context_files"] = [{"path": p} for p in self.ssh_context_files]
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

        sub_block = payload.get(SUB_SECTION, {})
        if isinstance(sub_block, dict) and sub_block:
            known["subs"] = {
                name: SubAgentSpec.from_dict(spec)
                for name, spec in sub_block.items()
                if isinstance(spec, dict)
            }

        section_keys: dict[str, set[str]] = {}
        for _, section, key in cls.section_bindings():
            section_keys.setdefault(section, set()).add(key)

        extra = dict(payload.get("extra", {}))
        top_level_skip = set(section_keys) | {"extra", SUB_SECTION} | cls.field_names()
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
        # Parse [[ssh.context_files]] array of tables
        ssh_block = payload.get("ssh", {})
        if isinstance(ssh_block, dict):
            context_files_raw = ssh_block.get("context_files", ())
            if isinstance(context_files_raw, list):
                known["ssh_context_files"] = tuple(
                    cf["path"]
                    for cf in context_files_raw
                    if isinstance(cf, dict) and cf.get("path")
                )
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

    def workspace_path_for(self, name: str) -> Path: ...

    @property
    def metainfo_path(self) -> Path: ...

    def load_metainfo(self) -> dict: ...

    def save_metainfo(self, metainfo: dict) -> None: ...

    @property
    def messages_conversation_id(self) -> str: ...

    def open_store(self) -> ConversationStore: ...

    def load_messages(self) -> Messages: ...

    async def open_sandbox(self, name: str = MAIN_WORKSPACE_NAME) -> Sandbox: ...

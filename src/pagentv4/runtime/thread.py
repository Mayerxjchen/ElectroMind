"""Thread —— 一段"跨轮次、跨启动的 agent 上下文"，绑一台伴身电脑。

# 什么是 Thread

Thread 是 pagentv4 里"agent 长期在这里干活"的最小完整实体。一个 thread_id 对应：

    <cwd>/.pagent/threads/<thread_id>/
        spec.json          # 沙箱/模型配置（首次冻结）
        messages.jsonl     # 对话历史（跨 turn、跨启动追加）
        workspace/         # 沙箱工作目录（Local 直接用，容器 bind mount 到这里）

一个 thread = **一段对话线索** + **一台沙箱电脑** + **一份文件工作目录**，三件事绑死。
命名参考 OpenAI Assistants API 和 Claude UI —— 用户在这些产品里已经有
"thread = 一段有状态、可回来续聊的对话" 的心智；这里把"电脑 + 文件"两侧一并挂进来。

# 边界

- **不是 run**：一次 `Agent.arun()` 是一个 run（若干 turn 组成的执行痕迹）。
  一个 thread 里可以先后跑多个 run，共享同一份 messages 和 sandbox。
- **不是 conversation**：conversation 只管消息；thread 还管沙箱身份。
  同一个 thread 换机器接着聊，能按 spec.json 把沙箱重建出来。
- **不是 sandbox**：sandbox 是"电脑"本体，进程/容器/远端连接；thread 是"这台电脑归谁、
  聊到哪、放什么文件"的账本。thread 每次开都要重新起一个 sandbox 实例。
- **不是 agent**：agent 是能力单元；thread 是它长期驻留的位置。

# 你能对 thread 做的四件事

围绕 thread 只有四个动作，没有别的：

- **建**：`Thread.open("foo", overrides={...})`，目录不存在时把 overrides 合进
  ThreadSpec 默认值写入 spec.json、mkdir workspace/，返回 `created=True`。
- **在里面干活**：同一个 thread_id 反复 open，拿到 spec 后起 sandbox、跑 agent。
  消息一直追加进 messages.jsonl，文件一直留在 workspace/，跨 turn、跨启动都在。
  spec.json 首次写完就冻结：后续 open 若带冲突的 overrides，冲突字段进
  `ignored_overrides`（调用方可提示用户"被忽略了"），实际仍以磁盘为准。
- **停**：什么都不用做。关掉 sandbox / 退出进程，thread 原样躺在磁盘上等下次 open。
- **切到另一条**：换一个 thread_id open 就是另一条 thread，各自独立的
  spec / 消息 / workspace，互不干扰。

要改一条已冻结 thread 的配置，就手改它的 spec.json，或直接 `rm -rf <thread dir>`
把整条删掉重建 —— 没有单独的"重置"开关。

# 谁调用它

只归 pagentv4.runtime；Sandbox / Agent 本身不认 Thread。REPL、CLI、上层门面用
Thread.open() 拿到 spec 后自行拼 Sandbox / Runner / JsonlConversationStore。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

THREAD_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$")
SPEC_FILENAME = "spec.json"
WORKSPACE_DIRNAME = "workspace"
MESSAGES_CONVERSATION_ID = "messages"


def default_threads_root() -> Path:
    """`<cwd>/.pagent/threads/`，可用 `PAGENT_THREADS_DIR` 覆盖。"""
    override = os.environ.get("PAGENT_THREADS_DIR")
    if override:
        return Path(os.path.abspath(override))
    return Path(os.getcwd()) / ".pagent" / "threads"


def validate_thread_id(thread_id: str) -> None:
    if not THREAD_ID_PATTERN.match(thread_id):
        raise ValueError(
            f"invalid thread_id: {thread_id!r}; "
            "must match [A-Za-z0-9][A-Za-z0-9_.-]{0,127}"
        )


@dataclass
class ThreadSpec:
    """一个 thread 的沙箱 + 模型配置；首次冻结、写进 spec.json。"""

    backend: str = "local"
    image: str | None = None
    container_ttl_seconds: int | None = None
    ssh_host: str | None = None
    ssh_config: str = "~/.ssh/config"
    ssh_workdir: str = "~/agent"
    model: str = "deepseek-v4-flash"
    system: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> ThreadSpec:
        known = {f: payload[f] for f in cls.field_names() if f in payload}
        unknown = {k: v for k, v in payload.items() if k not in cls.field_names()}
        if unknown:
            known.setdefault("extra", {}).update(unknown)
        return cls(**known)

    @classmethod
    def field_names(cls) -> set[str]:
        return {f.name for f in cls.__dataclass_fields__.values()}


@dataclass
class Thread:
    """一个 thread 的目录 handle：spec / messages / workspace 都从这里取路径。"""

    id: str
    root: Path
    spec: ThreadSpec
    created: bool
    ignored_overrides: tuple[str, ...] = ()

    @property
    def spec_path(self) -> Path:
        return self.root / SPEC_FILENAME

    @property
    def workspace_path(self) -> Path:
        return self.root / WORKSPACE_DIRNAME

    @property
    def messages_conversation_id(self) -> str:
        """messages.jsonl 走 JsonlConversationStore 存，conversation_id 用固定名。"""
        return MESSAGES_CONVERSATION_ID

    @classmethod
    def open(
        cls,
        thread_id: str,
        *,
        root: Path | str | None = None,
        overrides: dict | None = None,
    ) -> Thread:
        """打开或首次创建一个 thread。

        - 目录不存在：把 `overrides`（缺省 {}）合进 ThreadSpec 默认值写入 spec.json，
          mkdir workspace/。
        - 目录已存在：读 spec.json；`overrides` 里跟已存字段冲突的项被忽略，
          实际使用的 spec 仍以磁盘为准。`ignored_overrides` 记录哪些字段被丢了。
        """
        validate_thread_id(thread_id)
        base = Path(root) if root is not None else default_threads_root()
        thread_dir = base / thread_id
        spec_path = thread_dir / SPEC_FILENAME
        provided = dict(overrides or {})

        if spec_path.exists():
            payload = json.loads(spec_path.read_text(encoding="utf-8"))
            existing = ThreadSpec.from_dict(payload)
            ignored = cls.diff_overrides(existing, provided)
            thread_dir.mkdir(parents=True, exist_ok=True)
            (thread_dir / WORKSPACE_DIRNAME).mkdir(parents=True, exist_ok=True)
            return cls(
                id=thread_id,
                root=thread_dir,
                spec=existing,
                created=False,
                ignored_overrides=tuple(ignored),
            )

        spec = ThreadSpec(**provided) if provided else ThreadSpec()
        thread_dir.mkdir(parents=True, exist_ok=True)
        (thread_dir / WORKSPACE_DIRNAME).mkdir(parents=True, exist_ok=True)
        spec_path.write_text(
            json.dumps(spec.to_dict(), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return cls(id=thread_id, root=thread_dir, spec=spec, created=True)

    @staticmethod
    def diff_overrides(existing: ThreadSpec, overrides: dict) -> list[str]:
        ignored: list[str] = []
        for name, value in overrides.items():
            if name not in ThreadSpec.field_names() or name == "extra":
                continue
            if value != getattr(existing, name):
                ignored.append(name)
        return ignored

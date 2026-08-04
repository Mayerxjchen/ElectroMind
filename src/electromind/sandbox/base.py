"""Sandbox 类型定义。

设计目标：
- 沙箱是「伴身电脑」，可长期使用；实例本身不要求持久化。
- 工作目录是持久化载体：workspace_id 或宿主绝对路径 workdir 二选一。
- Backend 是「怎么落地这台电脑」，同一份 API 面向 local / docker / podman / ssh。

Backend 只关心「命令怎么跑、文件怎么读写」这两件事；
上层 Sandbox 门面负责 workspace 解析、生命周期、事件装配。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


class SandboxError(RuntimeError):
    """Sandbox 生命周期级错误的基类。

    与「命令级失败」区分:命令跑完但结果不成功(非零退出、超时)走
    ``CommandResult(ok=False)``,不抛异常;只有 sandbox 本身不可用(未启动、
    启动失败、后端死亡)才抛本类或其子类。上层可用 ``except SandboxError`` 兜住
    这一整类不可用状态。
    """


class SandboxNotStartedError(SandboxError):
    """在 ``start()`` 成功之前就调用了 exec / 文件操作。"""


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    """命令级别的软/硬约束。

    平台差异：
    - `timeout` 全部生效
    - `stdout_bytes` / `stderr_bytes` 全部生效（读取时截断）
    - `memory_bytes` / `cpu_seconds` 仅 POSIX 生效（rlimit）
    - 远程后端（ssh/docker）由后端自行决定是否落地
    """

    timeout: float | None = None
    stdout_bytes: int | None = 1024 * 1024
    stderr_bytes: int | None = 256 * 1024
    memory_bytes: int | None = None
    cpu_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class CommandResult:
    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    timed_out: bool = False


@dataclass(frozen=True, slots=True)
class DirEntry:
    name: str
    is_dir: bool
    size: int | None = None


@dataclass(frozen=True, slots=True)
class SandboxSpec:
    """Sandbox 启动参数。

    workspace 与 workdir 二者选一：
    - workspace_id: 逻辑名，宿主自动映射到 ~/.electromind/workspaces/<id>
    - workdir:      直接给宿主绝对路径

    home 是「agent 视角的工作根目录」（虚拟路径）。
    Sandbox 门面会把 home 前缀翻译成实际 workdir，所以 agent 换后端不用改 prompt。

    host_root 是「宿主机上允许 agent 观察/取文件的根目录」，默认 os.getcwd()：
    - copy_from_host 的 host_path 相对 host_root 解析；abs 也必须落在 host_root 之下
    - list_host_files 只能列 host_root 之下的内容
    - copy_to_host 只能把产物写到 <host_root>/artifacts/

    image / command / env / connection 由具体后端解读；
    Local 用不到 image；Docker/Podman 需要 image；SSH 需要 connection。

    container_ttl_seconds 只对容器 backend（docker / podman）生效：
    - None → 容器主进程为 `sleep infinity`，close() 时才被清掉
    - int  → 容器主进程为 `sleep <ttl>`，即使宿主进程被 kill -9，
             到期后 `--rm` 会让容器自杀清理，避免残留
    """

    workspace_id: str | None = None
    workdir: str | None = None
    home: str = "/home/agent"
    host_root: str | None = None
    image: str | None = None
    command: tuple[str, ...] | None = None
    env: dict[str, str] = field(default_factory=dict)
    connection: dict[str, str] = field(default_factory=dict)
    default_limits: SandboxLimits = field(default_factory=SandboxLimits)
    container_ttl_seconds: int | None = None
    command_policy: str = "open"
    tools: tuple[str, ...] = ()
    ssh_context_files: tuple[str, ...] = ()
    session_mode: str = "agent"  # ask | plan | agent | review
    autonomy: str = "prompt"  # prompt | auto-safe | full-access


@dataclass(frozen=True, slots=True)
class BackendIdentity:
    computer_name: str
    extra: str = ""


@runtime_checkable
class Backend(Protocol):
    """Sandbox 后端契约。

    每个后端实现 exec + files.* 两组方法。上层 Sandbox 只组合、不解析。
    workdir 是宿主视角的绝对路径，由 Sandbox 门面解析后传入；
    Backend 内部若需要挂载/切换，可以自己再映射（比如 Docker 挂到 /work）。

    错误处理口径（所有 backend 遵守同一约定）:
    - 命令级失败(命令跑起来了但退出码非零、或超时)由 ``exec`` 返回
      ``CommandResult(ok=False, ...)``,不抛异常。
    - 生命周期级错误(未 ``start`` 就调用、``start`` 自身失败、后端死亡)抛
      ``SandboxError`` 及其子类;未启动统一抛 ``SandboxNotStartedError``。
    - 配置/入参不合法(缺 image、缺 connection 等)在 ``start`` 阶段抛
      ``ValueError``。
    - 文件操作的语义级失败沿用标准异常(``FileNotFoundError`` /
      ``IsADirectoryError``),与生命周期错误区分。
    """

    async def start(self, spec: SandboxSpec, workdir: str) -> None: ...
    async def close(self) -> None: ...
    async def alive(self) -> bool:
        """后端还活着吗？（廉价探测，供 Guard 决策重启）

        - LocalBackend 总是 True
        - ContainerBackend 走 `<cli> inspect` 看容器 Running 状态
        - SSH/其它 backend 自行决定，比如 tcp 探活
        """
        ...

    async def exec(
        self,
        command: list[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        stdin: str | None = None,
        limits: SandboxLimits | None = None,
    ) -> CommandResult: ...

    async def read_file(self, path: str) -> bytes: ...
    async def write_file(self, path: str, data: bytes) -> None: ...
    async def list_dir(self, path: str) -> list[DirEntry]: ...
    async def exists(self, path: str) -> bool: ...
    async def remove(self, path: str, *, recursive: bool = False) -> None: ...

    def describe(self, spec: SandboxSpec, workdir: str) -> BackendIdentity:
        """自报家门：返回 computer_name + 与后端相关的 extra 段。

        os_info 与 uv 环境探测由 Sandbox 门面负责，backend 只描述自己独有的信息。
        """
        ...

    def effective_workdir(self) -> str | None:
        """backend 想让 Sandbox 门面用的 workdir 覆盖值。

        大多数 backend 直接使用 Sandbox 传入的宿主 workdir，返回 None 即可；
        SSH 之类跑在远端的 backend 返回远端路径（比如 /home/user/agent），
        Sandbox.start() 会用它覆盖 self.workdir，让后续 resolve / map_command
        路径直接是远端可用的。
        """
        return None

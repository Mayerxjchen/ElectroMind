"""Sandbox 门面 —— 面向用户的伴身电脑 API。

用法：
    async with await Sandbox.create(backend="local", workspace_id="my-project") as box:
        result = await box.commands.run("ls -la")
        await box.files.write("hello.txt", b"hi")
        content = await box.files.read("hello.txt")

Backend 只负责实现契约；Sandbox 组装 workspace + backend + 面向对象 API。

路径抽象（虚拟 home）：
- Agent 眼里的根目录是 `spec.home`（默认 `/home/agent`），跨 local / docker / ssh 一致。
- Sandbox 门面负责把 home 前缀翻译成后端实际接受的路径（宿主 workdir / 容器 home / 远端 workdir）。
- 相对路径按 home 拼接；绝对路径若在 home 之下也做翻译，其它一律拒绝，避免踩出工作目录。
"""

from __future__ import annotations

import os
import posixpath
import tarfile
import tempfile
from typing import TYPE_CHECKING

from .base import Backend, CommandResult, DirEntry, SandboxLimits, SandboxSpec
from .description import build_computer_description
from .guard import BackendGuard
from .policy import check_backend_path, check_command, validate_command_policy
from .workspace import resolve_workdir

if TYPE_CHECKING:
    from types import TracebackType


class Commands:
    def __init__(self, sandbox: Sandbox) -> None:
        self.sandbox = sandbox

    async def run(
        self,
        command: str | list[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        stdin: str | None = None,
        timeout: float | None = None,
        limits: SandboxLimits | None = None,
        trusted: bool = False,
    ) -> CommandResult:
        if isinstance(command, list):
            argv = [self.sandbox.map_command(part) for part in command]
            mapped = " ".join(argv)
        else:
            mapped = self.sandbox.map_command(command)
            argv = ["sh", "-c", mapped]

        if not trusted:
            try:
                check_command(
                    mapped,
                    workdir=self.sandbox.workdir,
                    policy=self.sandbox.spec.command_policy,
                )
            except PermissionError as exc:
                return CommandResult(
                    ok=False,
                    exit_code=126,
                    stdout="",
                    stderr=str(exc),
                    duration_seconds=0.0,
                )

        applied = limits
        if timeout is not None:
            base = limits or self.sandbox.spec.default_limits
            applied = SandboxLimits(
                timeout=timeout,
                stdout_bytes=base.stdout_bytes,
                stderr_bytes=base.stderr_bytes,
                memory_bytes=base.memory_bytes,
                cpu_seconds=base.cpu_seconds,
            )
        return await self.sandbox.backend.exec(
            argv,
            cwd=self.sandbox.resolve(cwd) if cwd else self.sandbox.workdir,
            env=env,
            stdin=stdin,
            limits=applied,
        )


class Files:
    def __init__(self, sandbox: Sandbox) -> None:
        self.sandbox = sandbox

    async def read(self, path: str) -> bytes:
        resolved = self.sandbox.resolve(path)
        check_backend_path(resolved, workdir=self.sandbox.workdir)
        return await self.sandbox.backend.read_file(resolved)

    async def read_text(self, path: str, encoding: str = "utf-8") -> str:
        raw = await self.read(path)
        return raw.decode(encoding)

    async def write(self, path: str, data: bytes | str) -> None:
        payload = data.encode("utf-8") if isinstance(data, str) else data
        resolved = self.sandbox.resolve(path)
        check_backend_path(resolved, workdir=self.sandbox.workdir)
        await self.sandbox.backend.write_file(resolved, payload)

    async def list(self, path: str = ".") -> list[DirEntry]:
        resolved = self.sandbox.resolve(path)
        check_backend_path(resolved, workdir=self.sandbox.workdir)
        return await self.sandbox.backend.list_dir(resolved)

    async def exists(self, path: str) -> bool:
        resolved = self.sandbox.resolve(path)
        check_backend_path(resolved, workdir=self.sandbox.workdir)
        return await self.sandbox.backend.exists(resolved)

    async def remove(self, path: str, *, recursive: bool = False) -> None:
        resolved = self.sandbox.resolve(path)
        check_backend_path(resolved, workdir=self.sandbox.workdir)
        await self.sandbox.backend.remove(resolved, recursive=recursive)

    async def str_replace(
        self,
        path: str,
        old_string: str,
        new_string: str,
        *,
        replace_all: bool = False,
    ) -> dict:
        """把文件里的 old_string 替换成 new_string。

        - 默认要求 old_string 在文件中唯一出现；出现多次时要求 `replace_all=True`。
        - 找不到 old_string / 出现多次且没开 replace_all → 返回 {ok: False, error}
        - 成功 → {ok: True, path, replacements}
        """
        content = await self.read_text(path)
        count = content.count(old_string)
        if count == 0:
            return {
                "ok": False,
                "path": path,
                "error": "文件中未找到 old_string。",
            }
        if count > 1 and not replace_all:
            return {
                "ok": False,
                "path": path,
                "error": (
                    f"old_string 出现了 {count} 次；"
                    "请提供更多上下文，或设置 replace_all=True。"
                ),
            }
        replacements = count if replace_all else 1
        new_content = content.replace(old_string, new_string, replacements)
        await self.write(path, new_content)
        return {"ok": True, "path": path, "replacements": replacements}


class Sandbox:
    ARTIFACTS_DIRNAME = "artifacts"
    SKILLS_DIRNAME = ".skills"

    def __init__(self, backend: Backend, spec: SandboxSpec, workdir: str) -> None:
        self.backend = backend
        self.spec = spec
        self.workdir = workdir
        self.home = spec.home
        self.host_root = spec.host_root or os.getcwd()
        self.commands = Commands(self)
        self.files = Files(self)
        self._started = False

    @classmethod
    async def create(
        cls,
        *,
        backend: str | Backend = "local",
        workspace_id: str | None = None,
        workdir: str | None = None,
        home: str = "/home/agent",
        host_root: str | None = None,
        image: str | None = None,
        command: tuple[str, ...] | None = None,
        env: dict[str, str] | None = None,
        connection: dict[str, str] | None = None,
        default_limits: SandboxLimits | None = None,
        container_ttl_seconds: int | None = None,
        command_policy: str = "open",
        auto_restart: bool = True,
        restart_max_attempts: int = 2,
    ) -> Sandbox:
        resolved_workdir = resolve_workdir(workspace_id=workspace_id, workdir=workdir)
        resolved_host_root = os.path.abspath(
            os.path.expanduser(host_root) if host_root else os.getcwd()
        )
        spec = SandboxSpec(
            workspace_id=workspace_id,
            workdir=resolved_workdir,
            home=home,
            host_root=resolved_host_root,
            image=image,
            command=command,
            env=dict(env or {}),
            connection=dict(connection or {}),
            default_limits=default_limits or SandboxLimits(),
            container_ttl_seconds=container_ttl_seconds,
            command_policy=validate_command_policy(command_policy),
        )
        instance = build_backend(backend) if isinstance(backend, str) else backend
        if auto_restart:
            instance = BackendGuard(instance, restart_max_attempts=restart_max_attempts)
        sandbox = cls(instance, spec, resolved_workdir)
        await sandbox.start()
        return sandbox

    async def start(self) -> None:
        if self._started:
            return
        await self.backend.start(self.spec, self.workdir)
        getter = getattr(self.backend, "effective_workdir", None)
        effective = getter() if callable(getter) else None
        if effective:
            self.workdir = effective
        self._started = True

    async def close(self) -> None:
        if not self._started:
            return
        await self.backend.close()
        self._started = False

    def safe_virtual_path(self, path: str) -> str:
        """把用户传入的路径规范成 home 相对路径（虚拟视角）。

        - 空 -> home
        - 已在 home 下 -> normpath
        - 其它绝对路径 -> ValueError
        - 相对路径 -> 拼接到 home
        """
        if not path:
            return self.home
        if path.startswith(self.home):
            normalized = posixpath.normpath(path)
        else:
            if posixpath.isabs(path):
                raise ValueError(f"path escapes sandbox home: {path!r}")
            normalized = posixpath.normpath(posixpath.join(self.home, path))
        if normalized == "/":
            raise ValueError("path must not resolve to filesystem root")
        if normalized != self.home and not normalized.startswith(f"{self.home}/"):
            raise ValueError(f"path escapes sandbox home: {path!r}")
        return normalized

    def resolve(self, path: str) -> str:
        """虚拟路径 -> 后端实际路径。"""
        virtual = self.safe_virtual_path(path)
        if virtual == self.home:
            return self.workdir
        relative = virtual.removeprefix(self.home).lstrip("/")
        return os.path.normpath(os.path.join(self.workdir, relative))

    def map_command(self, cmd: str) -> str:
        """把命令字符串里的虚拟 home 前缀替换成实际 workdir，让 shell 能识别。"""
        if not cmd or self.home == self.workdir:
            return cmd
        return cmd.replace(self.home, self.workdir)

    def to_virtual_path(self, actual: str) -> str:
        """后端实际路径 -> agent 视角的虚拟路径（供 list_dir / 输出映射用）。"""
        normalized = os.path.normpath(actual)
        workdir_norm = os.path.normpath(self.workdir)
        if normalized == workdir_norm:
            return self.home
        if not normalized.startswith(f"{workdir_norm}/"):
            return actual
        relative = normalized[len(workdir_norm) :].lstrip("/")
        return posixpath.join(self.home, relative.replace(os.sep, "/"))

    def resolve_host_path(self, path: str, *, allow_missing: bool = True) -> str:
        """把用户传入的 host 路径规范到 host_root 之下。

        规则：
        - 空 / '.' → host_root
        - 相对路径 → 拼到 host_root
        - abs 路径 → 必须落在 host_root 之下，否则 ValueError
        """
        root = os.path.abspath(self.host_root)
        raw = (path or "").strip() or "."
        candidate = os.path.expanduser(raw)
        if not os.path.isabs(candidate):
            candidate = os.path.join(root, candidate)
        resolved = os.path.normpath(os.path.abspath(candidate))
        if not (resolved == root or resolved.startswith(root + os.sep)):
            raise ValueError(f"host path escapes host_root: {path!r}")
        if not allow_missing and not os.path.exists(resolved):
            raise FileNotFoundError(f"host path not found: {resolved}")
        return resolved

    def display_host_path(self, actual: str) -> str:
        """host 绝对路径 → 相对 host_root 的展示路径（agent 视角）。"""
        root = os.path.abspath(self.host_root)
        normalized = os.path.normpath(os.path.abspath(actual))
        if normalized == root:
            return "."
        if normalized.startswith(root + os.sep):
            return normalized[len(root) + 1 :]
        return actual

    @property
    def artifacts_dir(self) -> str:
        """宿主机上默认的产物目录：<host_root>/artifacts/。"""
        return os.path.join(self.host_root, self.ARTIFACTS_DIRNAME)

    async def copy_from_host(self, host_path: str, dest: str = ".") -> str:
        """把宿主机文件或目录复制进 sandbox。返回 sandbox 内的虚拟路径。

        - `host_path`: 相对 host_root 或落在 host_root 之下的绝对路径
        - `dest`: sandbox 内的目标目录（虚拟路径），默认 home
        """
        source = self.resolve_host_path(host_path, allow_missing=False)
        if not os.path.exists(source):
            raise FileNotFoundError(f"host path not found: {source}")

        target_dir = self.safe_virtual_path(dest)
        name = os.path.basename(source.rstrip(os.sep)) or source.rstrip(os.sep)
        virtual_target = posixpath.join(target_dir, name)

        if os.path.isfile(source):
            backend_path = self.resolve(virtual_target)
            check_backend_path(backend_path, workdir=self.workdir)
            with open(source, "rb") as fp:
                await self.backend.write_file(backend_path, fp.read())
            return virtual_target

        if os.path.isdir(source):
            await self._copy_host_dir_archived(source, name)
            return virtual_target

        raise FileNotFoundError(f"host path is not a file or directory: {source}")

    async def _copy_host_dir_archived(self, host_dir: str, arcname: str) -> None:
        """Pack host directory as tar.gz, then extract into workspace."""
        with tempfile.NamedTemporaryFile(suffix=".tar.gz") as tmp:
            with tarfile.open(tmp.name, "w:gz") as tar:
                tar.add(host_dir, arcname=arcname)
            with tarfile.open(tmp.name, "r:gz") as tar:
                await self._extract_tar_to_workspace(tar)

    async def _extract_tar_to_workspace(self, tar: tarfile.TarFile) -> None:
        workdir = os.path.abspath(self.workdir)
        for member in tar.getmembers():
            if member.isdir():
                continue
            if not member.isfile():
                continue
            relative = member.name.replace("/", os.sep)
            if relative.startswith(os.sep) or ".." in relative.split(os.sep):
                raise ValueError(f"unsafe tar member: {member.name}")
            target = os.path.normpath(os.path.join(workdir, relative))
            if target != workdir and not target.startswith(workdir + os.sep):
                raise ValueError(f"unsafe tar member: {member.name}")
            payload = tar.extractfile(member)
            if payload is None:
                continue
            check_backend_path(target, workdir=self.workdir)
            await self.backend.write_file(target, payload.read())

    async def copy_to_host(self, source: str) -> str:
        """把 sandbox 里的文件复制到宿主机 artifacts/ 目录。返回宿主机实际路径。"""
        resolved = self.resolve(source)
        check_backend_path(resolved, workdir=self.workdir)
        payload = await self.backend.read_file(resolved)
        host_target_dir = self.artifacts_dir
        os.makedirs(host_target_dir, exist_ok=True)
        filename = posixpath.basename(source.rstrip("/")) or "artifact"
        dest = os.path.join(host_target_dir, filename)
        with open(dest, "wb") as fp:
            fp.write(payload)
        return dest

    def list_host_files(self, path: str = "", depth: int = 1) -> dict:
        """列出 host_root 下的文件/目录，供 agent 观察用户目录。

        - `path`: 相对 host_root 的路径；`""` / `"."` 表示 host_root 自身
        - `depth`: 1~3，默认 1；depth=1 只列直接子项，depth=n 递归展开 n 层
        """
        if depth < 1 or depth > 3:
            raise ValueError("depth must be 1..3")
        target = self.resolve_host_path(path, allow_missing=True)
        if not os.path.exists(target):
            return {
                "ok": False,
                "path": self.display_host_path(target),
                "error": "path not found",
                "entries": [],
            }
        if os.path.isfile(target):
            return {
                "ok": True,
                "path": self.display_host_path(target),
                "entries": [self.host_entry(target)],
            }
        entries = list(self.walk_host_dir(target, remaining=depth))
        return {
            "ok": True,
            "path": self.display_host_path(target),
            "entries": entries,
        }

    def walk_host_dir(self, target: str, *, remaining: int) -> list[dict]:
        """递归展开目录，最多 remaining 层。"""
        collected: list[dict] = []
        if remaining <= 0:
            return collected
        for name in sorted(os.listdir(target)):
            child = os.path.join(target, name)
            entry = self.host_entry(child)
            if entry["type"] == "dir" and remaining > 1:
                entry["children"] = self.walk_host_dir(child, remaining=remaining - 1)
            collected.append(entry)
        return collected

    def host_entry(self, actual: str) -> dict:
        is_dir = os.path.isdir(actual)
        size = None if is_dir else os.path.getsize(actual)
        return {
            "name": os.path.basename(actual),
            "path": self.display_host_path(actual),
            "type": "dir" if is_dir else "file",
            "size": size,
        }

    def tools(self):
        """把 sandbox 能力包装成 agent 工具列表。"""
        from .tools import build_sandbox_tools

        return build_sandbox_tools(self)

    async def install_skills(self, registry) -> dict[str, str]:
        """把 SkillRegistry 里的 skill 拷进 sandbox 的 `<home>/.skills/<name>/`。

        - 返回 `{skill_name: agent 视角路径}` 映射；上层拿去传给
          `make_use_skill_tool` / `build_skills_system_prompt` 就能让 agent
          看到自己电脑上的路径。
        - 逐文件用 `backend.write_file` 写，对所有 backend 都一致。
        - 二次调用会覆盖同名文件，方便热更新 skill。
        """
        mount: dict[str, str] = {}
        for skill in registry.list():
            base = posixpath.join(self.home, self.SKILLS_DIRNAME, skill.name)
            await self.files.write(
                posixpath.join(base, "SKILL.md"),
                (skill.root / "SKILL.md").read_bytes(),
            )
            for rel in skill.resources:
                await self.files.write(
                    posixpath.join(base, rel),
                    (skill.root / rel).read_bytes(),
                )
            mount[skill.name] = base
        return mount

    async def describe(self) -> str:
        """自报家门：拼一段 system prompt 描述这台电脑。

        - 系统信息统一走 `uname -a`；后端不必自己实现。
        - backend.describe() 只描述自己特有的部分（宿主 workdir、远端连接串、镜像等）。
        - uv 环境探测通过同一个 run_probe 完成。
        """
        os_info = await self.probe_os_info()
        identity = self.backend.describe(self.spec, self.workdir)
        return await build_computer_description(
            computer_name=identity.computer_name,
            os_info=os_info,
            home=self.home,
            host_root=self.host_root,
            artifacts_dir=self.ARTIFACTS_DIRNAME,
            extra=identity.extra,
            run_probe=self.run_probe,
        )

    async def probe_os_info(self) -> str:
        result = await self.commands.run("uname -a", trusted=True)
        if result.ok:
            return result.stdout.strip() or "unknown"
        return "unknown"

    async def run_probe(self, command: str) -> dict:
        """给 description 用的探测器：只关心 ok / exit_code。"""
        result = await self.commands.run(command, trusted=True)
        return {"ok": result.ok, "exit_code": result.exit_code}

    async def __aenter__(self) -> Sandbox:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()


def build_backend(name: str) -> Backend:
    key = name.lower()
    if key == "local":
        from .backends.local import LocalBackend

        return LocalBackend()
    if key == "docker":
        from .backends.docker import DockerBackend

        return DockerBackend()
    if key == "podman":
        from .backends.podman import PodmanBackend

        return PodmanBackend()
    if key == "ssh":
        from .backends.ssh import SshBackend

        return SshBackend()
    raise ValueError(
        f"unknown backend: {name!r}; expected one of local/docker/podman/ssh"
    )

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
import shutil
import tarfile
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from .base import (
    Backend,
    CommandResult,
    DirEntry,
    SandboxError,
    SandboxLimits,
    SandboxSpec,
)
from .description import build_computer_description
from .guard import BackendGuard
from .policy import check_backend_path, check_command, validate_command_policy
from .workspace import resolve_workdir

if TYPE_CHECKING:
    from types import TracebackType

    from electromind.skills.discovery import SkillMount


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

        # Session-mode enforcement (Ask / Plan / Agent)
        if not trusted:
            from .mode_guard import SessionMode, check_command_exec

            mode = SessionMode(self.sandbox.spec.session_mode)
            mode_check = check_command_exec(mode, command)
            if not mode_check.allowed:
                return CommandResult(
                    ok=False,
                    exit_code=126,
                    stdout="",
                    stderr=mode_check.reason,
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
        result = await self.sandbox.backend.exec(
            argv,
            cwd=self.sandbox.resolve(cwd) if cwd else self.sandbox.workdir,
            env=env,
            stdin=stdin,
            limits=applied,
        )
        # Audit every command execution
        from .audit import AuditEntry

        self.sandbox.audit.record(
            AuditEntry(
                timestamp=time.time(),
                thread_id=getattr(self.sandbox.spec, "workspace_id", "") or "",
                operation="command_exec",
                target=mapped,
                autonomy=self.sandbox.spec.autonomy,
                session_mode=self.sandbox.spec.session_mode,
                backend=self.sandbox.spec.connection.get("host", "local")
                if self.sandbox.spec.connection
                else "local",
                isolated=self.sandbox._is_isolated,
                outcome="allowed" if result.ok else "error",
                detail=result.stderr[:200] if not result.ok else "",
            )
        )
        return result


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

    async def write(
        self, path: str, data: bytes | str, *, _internal: bool = False
    ) -> None:
        # Internal operations (skill catalog install, sandbox bootstrap) bypass
        # the session mode guard — only user-initiated writes are gated.
        if not _internal:
            from .mode_guard import SessionMode, check_file_write

            mode = SessionMode(self.sandbox.spec.session_mode)
            check = check_file_write(mode)
            if not check.allowed:
                raise PermissionError(check.reason)
        payload = data.encode("utf-8") if isinstance(data, str) else data
        resolved = self.sandbox.resolve(path)
        check_backend_path(resolved, workdir=self.sandbox.workdir)
        await self.sandbox.backend.write_file(resolved, payload)
        # Audit file writes
        from .audit import AuditEntry

        self.sandbox.audit.record(
            AuditEntry(
                timestamp=time.time(),
                thread_id=getattr(self.sandbox.spec, "workspace_id", "") or "",
                operation="file_write",
                target=path,
                autonomy=self.sandbox.spec.autonomy,
                session_mode=self.sandbox.spec.session_mode,
                backend="local",
                isolated=self.sandbox._is_isolated,
                outcome="allowed",
            )
        )

    async def list(self, path: str = ".") -> list[DirEntry]:
        resolved = self.sandbox.resolve(path)
        check_backend_path(resolved, workdir=self.sandbox.workdir)
        return await self.sandbox.backend.list_dir(resolved)

    async def exists(self, path: str) -> bool:
        resolved = self.sandbox.resolve(path)
        check_backend_path(resolved, workdir=self.sandbox.workdir)
        return await self.sandbox.backend.exists(resolved)

    async def remove(
        self, path: str, *, recursive: bool = False, _internal: bool = False
    ) -> None:
        # Internal operations bypass the session mode guard.
        if not _internal:
            from .mode_guard import SessionMode, check_file_delete

            mode = SessionMode(self.sandbox.spec.session_mode)
            check = check_file_delete(mode)
            if not check.allowed:
                raise PermissionError(check.reason)
        resolved = self.sandbox.resolve(path)
        check_backend_path(resolved, workdir=self.sandbox.workdir)
        await self.sandbox.backend.remove(resolved, recursive=recursive)
        # Audit file deletes
        from .audit import AuditEntry

        self.sandbox.audit.record(
            AuditEntry(
                timestamp=time.time(),
                thread_id=getattr(self.sandbox.spec, "workspace_id", "") or "",
                operation="file_delete",
                target=path,
                autonomy=self.sandbox.spec.autonomy,
                session_mode=self.sandbox.spec.session_mode,
                backend="local",
                isolated=self.sandbox._is_isolated,
                outcome="allowed",
            )
        )

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
        self._last_catalog_fingerprint: str | None = None
        self._last_catalog_mounts: dict[str, SkillMount] = {}
        self._last_source_digests: dict[str, str] = {}
        # Security audit trail
        from .audit import AuditLog

        self.audit = AuditLog(workdir)
        self._is_isolated = spec.session_mode != "local" and backend is not None

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
        tools: tuple[str, ...] = (),
        ssh_context_files: tuple[str, ...] = (),
        session_mode: str = "agent",
        autonomy: str = "prompt",
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
            tools=tuple(tools),
            ssh_context_files=ssh_context_files,
            session_mode=session_mode,
            autonomy=autonomy,
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
            try:
                entry = self.host_entry(child)
            except FileNotFoundError:
                continue
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

    async def install_skill_snapshot(
        self, snapshot_dir: str | Path, digest: str
    ) -> str:
        """Install ONE skill snapshot into the sandbox (SKILL-5 lazy mount).

        Copies the content-addressed snapshot directory
        (``<snapshot>/SKILL.md`` + ``resources/``) into
        ``<home>/.skills/<digest[:8]>/`` using the same staging + atomic
        rename machinery as ``install_skill_catalog``.

        - Content-addressed path: same digest → same target → idempotent;
          re-activating an already-mounted digest skips the copy.
        - Only the activated skill is transferred — discovering 100 skills
          and activating one sends exactly one skill into the environment.

        Returns the agent-visible mounted root.
        """
        import uuid

        dgst = digest[:8]
        target_dir = posixpath.join(self.home, self.SKILLS_DIRNAME, dgst)
        resolved_target = self.resolve(target_dir)
        if await self.files.exists(target_dir):
            # Same digest already mounted — content-addressed reuse.
            return target_dir

        staging_name = f"skill-{uuid.uuid4().hex[:8]}"
        staging_dir = posixpath.join(
            self.home, self.SKILLS_DIRNAME, ".staging", staging_name
        )
        resolved_staging = self.resolve(staging_dir)
        await self._ensure_dir(staging_dir)

        try:
            src = Path(snapshot_dir)
            for dirpath, dirnames, filenames in os.walk(src):
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                for filename in sorted(filenames):
                    if filename.startswith("."):
                        continue
                    full = Path(dirpath) / filename
                    rel = full.relative_to(src).as_posix()
                    target = posixpath.join(staging_dir, rel)
                    await self.files.write(target, full.read_bytes(), _internal=True)

            # Atomic rename: staging → final
            await self._ensure_dir(posixpath.join(self.home, self.SKILLS_DIRNAME))
            mv_result = await self.backend.exec(
                ["mv", resolved_staging, resolved_target],
                cwd=self.workdir,
                limits=SandboxLimits(timeout=30),
            )
            if not mv_result.ok:
                raise RuntimeError(f"mv staging → target failed: {mv_result.stderr}")
            return target_dir
        except Exception:
            # Clean up staging on failure
            try:
                await self.backend.exec(
                    ["rm", "-rf", resolved_staging],
                    cwd=self.workdir,
                    limits=SandboxLimits(timeout=30),
                )
            except Exception:
                pass
            raise

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

    async def install_skill_catalog(
        self, snapshot, *, skill_set_snapshot=None
    ) -> dict[str, "SkillMount"]:
        """Install every source in a ``SkillCatalogSnapshot`` into the sandbox.

        Layout rules:

        - Paths include a content digest prefix:
          ``<home>/.skills/<source-id>/<digest[:8]>/``.
        - Installation uses a staging directory with atomic rename — a failed
          install leaves no partial content.
        - **Standard source** target: ``<digest>/<skill-name>/``.
        - **Structured source** target: ``<digest>/`` (complete root).
        - All writes go through ``self.files.write``; no shell, tar, or cp.
        - Symlinks that resolve outside the declared source root are skipped.
        - When the fingerprint matches the last successful install, mounts are
          returned without rewriting files.

        If *skill_set_snapshot* (a ``SkillSetSnapshot``) is provided, staging
        content is verified against its frozen per-resource SHA-256 hashes
        instead of re-reading live source files (closes the TOCTOU window).

        Returns:
            ``{public_skill_name: SkillMount}`` mapping.
        """
        import uuid

        # Cache hit — fingerprint unchanged
        if self._last_catalog_fingerprint == snapshot.fingerprint:
            return dict(self._last_catalog_mounts)

        mounts: dict[str, SkillMount] = {}
        staging_base = posixpath.join(self.home, self.SKILLS_DIRNAME, ".staging")

        for source in snapshot.sources:
            source_root = source.root
            source_id = source.id

            # Compute a content digest for this source
            source_digest = _compute_source_digest(source, snapshot)
            dgst = source_digest[:8]

            # Skip sources with no matching skills
            source_skills = [
                s
                for s in snapshot.registry.list()
                if getattr(s, "source_id", "") == source_id
            ]
            if not source_skills:
                continue

            # Check cache by source digest
            cache_key = f"{source_id}:{source_digest}"
            if self._last_source_digests.get(source_id) == cache_key:
                # Reuse existing mounts for this source
                for skill in snapshot.registry.list():
                    if getattr(skill, "source_id", "") != source_id:
                        continue
                    if skill.name in mounts:
                        continue
                    # Reconstruct mount path from cached digest
                    mounts[skill.name] = _build_source_mount(
                        source, skill, dgst, self.home, self.SKILLS_DIRNAME
                    )
                continue

            # ── Staging ──────────────────────────────────────────
            staging_name = f"{source_id}-{uuid.uuid4().hex[:8]}"
            staging_dir = posixpath.join(staging_base, staging_name)

            try:
                if source.kind == "structured":
                    # Copy complete structured skill root into staging
                    await self._copy_directory_tree(
                        source_root, staging_dir, source_root
                    )
                else:
                    # Copy each skill directory into staging
                    for skill in snapshot.registry.list():
                        if getattr(skill, "source_id", "") != source_id:
                            continue
                        host_dir = skill.root.resolve()
                        await self._copy_directory_tree(
                            host_dir, staging_dir, host_dir.parent
                        )

                # ── Verify staging content ─────────────────────
                await _verify_staging_content(
                    self, staging_dir, source, snapshot, skill_set_snapshot
                )

                # ── Atomic rename: staging → final ───────────────
                target_dir = posixpath.join(
                    self.home, self.SKILLS_DIRNAME, source_id, dgst
                )
                target_parent = posixpath.join(
                    self.home, self.SKILLS_DIRNAME, source_id
                )

                # Ensure parent exists
                await self._ensure_dir(target_parent)

                # Remove previous digest for this source if present
                try:
                    resolved_target = self.resolve(target_dir)
                    await self.backend.exec(
                        ["rm", "-rf", resolved_target],
                        cwd=self.workdir,
                        limits=SandboxLimits(timeout=30),
                    )
                except Exception:
                    pass

                # Atomic rename
                resolved_staging = self.resolve(staging_dir)
                mv_result = await self.backend.exec(
                    ["mv", resolved_staging, resolved_target],
                    cwd=self.workdir,
                    limits=SandboxLimits(timeout=30),
                )
                if not mv_result.ok:
                    raise RuntimeError(
                        f"mv staging → target failed: {mv_result.stderr}"
                    )

                # Clean up old digest dirs for this source
                await _cleanup_old_digest_dirs(self, source_id, dgst)

                # Record success
                self._last_source_digests[source_id] = cache_key

            except Exception:
                # Clean up staging on any failure
                try:
                    resolved_staging = self.resolve(staging_dir)
                    await self.backend.exec(
                        ["rm", "-rf", resolved_staging],
                        cwd=self.workdir,
                        limits=SandboxLimits(timeout=30),
                    )
                except Exception:
                    pass
                raise

        # Build all mounts
        for source in snapshot.sources:
            source_id = source.id
            cache_key = self._last_source_digests.get(source_id, "")
            dgst = cache_key.split(":")[-1][:8] if ":" in cache_key else ""
            if not dgst:
                dgst = _compute_source_digest(source, snapshot)[:8]

            for skill in snapshot.registry.list():
                if getattr(skill, "source_id", "") != source_id:
                    continue
                if skill.name in mounts:
                    continue
                mounts[skill.name] = _build_source_mount(
                    source, skill, dgst, self.home, self.SKILLS_DIRNAME
                )

        self._last_catalog_fingerprint = snapshot.fingerprint
        self._last_catalog_mounts = dict(mounts)
        return mounts

    async def _ensure_dir(self, path: str) -> None:
        """Create directory *path* in the sandbox (mkdir -p)."""
        resolved = self.resolve(path)
        result = await self.backend.exec(
            ["mkdir", "-p", resolved],
            cwd=self.workdir,
            limits=SandboxLimits(timeout=30),
        )
        if not result.ok:
            raise RuntimeError(f"mkdir -p {path} failed: {result.stderr}")

    async def _copy_directory_tree(
        self, host_dir: Path, sandbox_target: str, allowed_root: Path
    ) -> None:
        """Recursively copy *host_dir* into *sandbox_target* using ``self.files.write``.

        Rejects any file or symlink that resolves outside *allowed_root*.
        """
        for dirpath, dirnames, filenames in os.walk(host_dir):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for filename in sorted(filenames):
                if filename.startswith("."):
                    continue
                full = Path(dirpath) / filename
                # Resolve symlinks and reject escapes
                try:
                    resolved = full.resolve()
                except OSError:
                    continue
                if not _is_within(resolved, allowed_root.resolve()):
                    continue
                rel = resolved.relative_to(allowed_root.resolve()).as_posix()
                target = posixpath.join(sandbox_target, rel)
                await self.files.write(target, resolved.read_bytes(), _internal=True)

    async def describe(self) -> str:
        """自报家门：拼一段 system prompt 描述这台电脑。

        - 系统信息统一走 `uname -a`；后端不必自己实现。
        - backend.describe() 只描述自己特有的部分（宿主 workdir、远端连接串、镜像等）。
        - uv 环境探测通过同一个 run_probe 完成。
        """
        os_info = await self.probe_os_info()
        identity = self.backend.describe(self.spec, self.workdir)
        from .tools import resolve_tool_names

        return await build_computer_description(
            computer_name=identity.computer_name,
            os_info=os_info,
            home=self.home,
            host_root=self.host_root,
            artifacts_dir=self.ARTIFACTS_DIRNAME,
            extra=identity.extra,
            tool_names=resolve_tool_names(self.spec.tools),
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


CONTAINER_CLI_PREFERENCE = ("docker", "podman")


def _is_within(path: Path, root: Path) -> bool:
    """Return True if *path* equals *root* or is a descendant.

    Both *path* and *root* are resolved before comparison to prevent
    symlink escapes from bypassing the containment check.
    """
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def detect_container_cli() -> str:
    """探测 PATH 里可用的容器 CLI，按 docker → podman 顺序返回第一个。

    给 backend="container" 用：用户不关心装的是 docker 还是 podman，运行时探测即可。
    两者都不在 PATH 时抛 SandboxError，让上层给出明确的安装提示。
    """
    for cli in CONTAINER_CLI_PREFERENCE:
        if shutil.which(cli):
            return cli
    joined = " / ".join(CONTAINER_CLI_PREFERENCE)
    raise SandboxError(f"no container CLI found in PATH; install one of: {joined}")


def build_backend(name: str) -> Backend:
    key = name.lower()
    if key == "local":
        from .backends.local import LocalBackend

        return LocalBackend()
    if key == "container":
        return build_backend(detect_container_cli())
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
        f"unknown backend: {name!r}; expected one of local/container/docker/podman/ssh"
    )


class SandboxProfile(Protocol):
    """open_sandbox_for_spec 需要的字段；ThreadSpec 结构上即满足此协议。

    放在 sandbox 层，让「哪个 backend 要哪些字段」的知识收敛于此，Thread 只提供
    profile 与 workdir，不感知 backend 种类。
    """

    backend: str
    image: str | None
    container_ttl_seconds: int | None
    ssh_host: str | None
    ssh_config: str
    ssh_workdir: str
    ssh_context_files: tuple[str, ...]
    command_policy: str
    session_mode: str
    autonomy: str
    project_path: str | None
    sandbox_tools: tuple[str, ...]


def profile_host_root(profile: SandboxProfile) -> str | None:
    """用户 project → sandbox host_root；未绑定则 None（回退 cwd）。"""
    raw = getattr(profile, "project_path", None)
    if not isinstance(raw, str) or not raw.strip():
        return None
    return os.path.abspath(os.path.expanduser(raw.strip()))


async def open_sandbox_for_spec(
    profile: SandboxProfile,
    workdir: str,
    *,
    label: str = "",
) -> Sandbox:
    """按 profile 声明的 backend 打开 sandbox，负责字段映射与前置校验。

    各 backend 对字段的要求（docker/podman 必须有 image、ssh 必须有 ssh_host 并解析
    ~/.ssh/config）都在此处理，新增 backend 只改这里，不改 Thread。

    Args:
        profile: 满足 SandboxProfile 的配置对象（如 ThreadSpec）。
        workdir: agent 沙箱工作目录（宿主路径，通常是 thread/workspace）。
        label: 出错信息里的调用方标识（如 thread id），仅用于报错可读性。

    Returns:
        已 start 的 Sandbox。

    Raises:
        ValueError: backend 不认识，或必需字段缺失。
    """
    prefix = f"{label}: " if label else ""
    backend = profile.backend
    host_root = profile_host_root(profile)
    tools = tuple(getattr(profile, "sandbox_tools", ()) or ())
    session_mode = getattr(profile, "session_mode", "agent") or "agent"
    autonomy = getattr(profile, "autonomy", "prompt") or "prompt"

    if backend == "local":
        return await Sandbox.create(
            backend="local",
            workdir=workdir,
            host_root=host_root,
            command_policy=profile.command_policy,
            tools=tools,
            session_mode=session_mode,
            autonomy=autonomy,
        )

    if backend in ("container", "docker", "podman"):
        if not profile.image:
            raise ValueError(f"{prefix}backend {backend!r} requires image")
        return await Sandbox.create(
            backend=backend,
            workdir=workdir,
            host_root=host_root,
            image=profile.image,
            container_ttl_seconds=profile.container_ttl_seconds,
            command_policy=profile.command_policy,
            tools=tools,
            session_mode=session_mode,
            autonomy=autonomy,
        )

    if backend == "ssh":
        if not profile.ssh_host:
            raise ValueError(f"{prefix}backend 'ssh' requires ssh_host")
        from .backends.ssh import SshConnection

        conn = SshConnection.from_ssh_config(
            profile.ssh_host,
            config_path=profile.ssh_config,
            workdir=profile.ssh_workdir,
        )
        return await Sandbox.create(
            backend="ssh",
            workdir=workdir,
            host_root=host_root,
            connection=conn.to_dict(),
            command_policy=profile.command_policy,
            tools=tools,
            ssh_context_files=getattr(profile, "ssh_context_files", ()),
            session_mode=session_mode,
            autonomy=autonomy,
        )

    raise ValueError(
        f"{prefix}unknown backend: {backend!r}; "
        "expected one of local/container/docker/podman/ssh"
    )


# ---------------------------------------------------------------------------
# Skill catalog install helpers
# ---------------------------------------------------------------------------


def _compute_source_digest(source, snapshot) -> str:
    """Compute a content hash for all skills from a single source.

    Covers skill identities and actual resource file content, so any
    change to a resource file changes the digest.
    """
    import hashlib

    h = hashlib.sha256()
    for skill in sorted(snapshot.registry.list(), key=lambda s: s.name):
        if getattr(skill, "source_id", "") != source.id:
            continue
        h.update(skill.name.encode("utf-8"))
        h.update(skill.sha256.encode("utf-8"))
        for res in sorted(skill.resources):
            h.update(res.encode("utf-8"))
            # Hash resource content for tamper detection.
            # Prefer skill.skill_root — __post_init__ guarantees it is set.
            skill_dir = getattr(skill, "skill_root", None) or getattr(
                skill, "root", None
            )
            res_path = (skill_dir / res) if skill_dir is not None else None
            if res_path is not None:
                try:
                    file_hash, _ = _hash_file(res_path)
                    h.update(file_hash.encode("utf-8"))
                except OSError:
                    h.update(b"unreadable")
    return h.hexdigest()


def _hash_file(path) -> tuple[str, int]:
    """Return ``(sha256_hex, size_bytes)`` for a file."""
    import hashlib

    h = hashlib.sha256()
    size = 0
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


async def _verify_staging_content(
    sandbox, staging_dir: str, source, snapshot, skill_set_snapshot=None
) -> None:
    """Verify staging files match expected content hashes.

    When *skill_set_snapshot* is provided, uses its frozen per-resource
    SHA-256 hashes (``SkillResource.sha256``) keyed by the staging-relative
    path ``<relative_root>/<resource_path>``.  Otherwise falls back to
    re-reading live source files.

    Every expected file must be present in staging with a matching hash;
    every staging file must correspond to an expected resource.  Directory
    traversal failures are fatal.

    Raises ``RuntimeError`` on mismatch, missing file, extra file, or
    unreadable staging content.
    """
    import hashlib
    import posixpath

    # Build expected hashes — prefer frozen snapshot, fall back to live files
    expected: dict[str, str] = {}  # staging_relative_path -> sha256
    if skill_set_snapshot is not None:
        # Use immutable snapshot hashes (no TOCTOU window).
        # Key = relative_root + "/" + resource.relative_path, which
        # matches the layout produced by _copy_directory_tree.
        for ss in skill_set_snapshot.skills:
            if getattr(ss, "source_id", "") != source.id:
                continue
            skill_prefix = (ss.relative_root + "/") if ss.relative_root else ""
            # Track SKILL.md hash for full-bundle verification
            if getattr(ss, "skill_md_sha256", ""):
                expected[skill_prefix + "SKILL.md"] = ss.skill_md_sha256
            for res in ss.resources:
                staging_key = skill_prefix + res.relative_path
                expected[staging_key] = res.sha256
        # Track AGENTS.md for structured sources — per-source hash
        if source.kind == "structured":
            agents_hashes = getattr(skill_set_snapshot, "agents_md_hashes", ())
            for src_id, fh in agents_hashes:
                if src_id == source.id:
                    expected["AGENTS.md"] = fh
                    break
    else:
        # Fallback: re-hash live source files.
        # Build staging-relative keys that match _copy_directory_tree output.
        for skill in snapshot.registry.list():
            if getattr(skill, "source_id", "") != source.id:
                continue
            # Compute prefix that matches staging layout:
            #   structured: skill_root relative to source_root
            #   standard:   skill root directory name
            skill_root = skill.root.resolve() if hasattr(skill, "root") else None
            if skill_root is None:
                continue
            try:
                prefix = skill_root.relative_to(source.root.resolve()).as_posix()
            except ValueError:
                prefix = skill_root.name
            prefix = (prefix + "/") if prefix else ""
            for res in skill.resources:
                res_path = (skill.root / res) if hasattr(skill, "root") else None
                if res_path is None:
                    continue
                try:
                    fh, _ = _hash_file(res_path)
                    expected[prefix + res] = fh
                except OSError:
                    continue

    if not expected:
        return  # Source has no tracked resources

    # Recursively walk staging; verify every file and track coverage
    found: set[str] = set()

    async def _walk_verify(base: str, rel_prefix: str) -> None:
        try:
            entries = await sandbox.files.list(base)
        except Exception as exc:
            raise RuntimeError(
                f"Staging verification failed: cannot list {base}: {exc}"
            ) from exc
        for entry in entries:
            if entry.name.startswith("."):
                continue
            entry_rel = (
                posixpath.join(rel_prefix, entry.name) if rel_prefix else entry.name
            )
            entry_path = posixpath.join(base, entry.name)
            if entry.is_dir:
                await _walk_verify(entry_path, entry_rel)
                continue
            # Verify only tracked resources; skip non-resource files
            # (structured sources include AGENTS.md, knowledge/, etc.)
            exp_hash = expected.get(entry_rel)
            if exp_hash is None:
                continue
            # Read and verify content
            try:
                content = await sandbox.files.read(entry_path)
                actual_hash = hashlib.sha256(content).hexdigest()
            except Exception as exc:
                raise RuntimeError(
                    f"Staging verification failed: cannot read {entry_path}: {exc}"
                ) from exc
            if actual_hash != exp_hash:
                raise RuntimeError(
                    f"Staging content mismatch for {entry_rel!r}: "
                    f"expected sha256={exp_hash[:16]}..., "
                    f"got {actual_hash[:16]}..."
                )
            found.add(entry_rel)

    await _walk_verify(staging_dir, "")

    # Every expected resource must be present in staging
    missing = set(expected.keys()) - found
    if missing:
        raise RuntimeError(
            f"Staging verification failed: {len(missing)} expected "
            f"resource(s) not found in staging: {sorted(missing)}"
        )


def _build_source_mount(
    source, skill, digest_prefix: str, home: str, skills_dir: str
) -> "SkillMount":
    """Build a ``SkillMount`` for a skill installed at a digest-prefixed path."""
    import posixpath

    from electromind.skills.discovery import SkillMount

    source_id = source.id
    target_base = posixpath.join(home, skills_dir, source_id, digest_prefix)

    if source.kind == "structured":
        source_root = source.root
        skill_dir = getattr(skill, "skill_root", None) or skill.root
        try:
            rel = skill_dir.resolve().relative_to(source_root.resolve()).as_posix()
        except ValueError:
            rel = skill_dir.name
        skill_target = posixpath.join(target_base, rel)
        return SkillMount(
            source_root=source_id,
            skill_root=skill_target,
            skills_root=target_base,
        )
    else:
        host_dir = skill.root.resolve()
        skill_target = posixpath.join(target_base, host_dir.name)
        return SkillMount(
            source_root=source_id,
            skill_root=skill_target,
            skills_root=None,
        )


async def _cleanup_old_digest_dirs(
    sandbox: "Sandbox", source_id: str, keep_prefix: str
) -> None:
    """Remove old digest-prefix directories for *source_id*, keeping *keep_prefix*."""
    import posixpath

    source_dir = posixpath.join(sandbox.home, sandbox.SKILLS_DIRNAME, source_id)
    try:
        entries = await sandbox.files.list(source_dir)
    except Exception:
        return
    for entry in entries:
        if (
            entry.is_dir
            and entry.name != keep_prefix
            and not entry.name.startswith(".")
        ):
            try:
                entry_path = posixpath.join(source_dir, entry.name)
                resolved_entry = sandbox.resolve(entry_path)
                await sandbox.backend.exec(
                    ["rm", "-rf", resolved_entry],
                    cwd=sandbox.workdir,
                    limits=SandboxLimits(timeout=30),
                )
            except Exception:
                pass

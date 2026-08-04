"""SKILL-5 tests: single-skill lazy mounting.

Completion criterion: discover 100 skills, activate 1 → the execution
environment receives exactly 1.
"""

import os as _os
from pathlib import Path

import pytest
from skill_helpers import make_skill_dirs

from electromind import Sandbox
from electromind.skills.activation import ActivationRequest, SkillActivationService
from electromind.skills.catalog import build_catalog
from electromind.skills.mounting import LazySkillMounter
from electromind.skills.scopes import discover_candidate_sources, load_candidates
from electromind.skills.snapstore import PrivateSnapshotStore


@pytest.mark.asyncio
async def test_lazy_mount_installs_one_of_many(tmp_path):
    """发现 100 个 Skill、激活 1 个时，执行环境只接收 1 个。"""
    # ── 100 discovered skills in the project ────────────────────────────
    project = tmp_path / "proj"
    project.mkdir()
    skills_root = project / ".agents" / "skills"
    skills_root.mkdir(parents=True)
    make_skill_dirs(skills_root, 100)

    sources = discover_candidate_sources(
        str(project), cwd=str(project), builtin_roots=()
    )
    candidates = load_candidates(sources)
    assert len(candidates) == 100

    catalog = build_catalog(
        candidates, generation=1, cwd=str(project), repo_root=str(project)
    )

    # ── Activate exactly one ─────────────────────────────────────────────
    target = next(c for c in candidates if c.descriptor.name == "skill-042")
    store = PrivateSnapshotStore(tmp_path / "snapshots")

    async with await Sandbox.create(
        backend="local", workdir=str(tmp_path / "box")
    ) as box:
        mounter = LazySkillMounter(box, store=store)
        service = SkillActivationService(
            catalog, store=store, mounter=mounter, items_dir=tmp_path / "items"
        )
        result = await service.activate(
            ActivationRequest(
                request_id="req-1",
                thread_id="t1",
                run_id="run-1",
                skill_id=target.skill_id,
            )
        )

        mounted = result.item.mounted_root
        assert mounted is not None
        # The mounted root is content-addressed
        assert mounted.startswith("/home/agent/.skills/")
        # Exactly one skill directory exists in the sandbox
        import os as _os

        skills_dir = box.resolve("/home/agent/.skills")
        assert _os.path.isdir(skills_dir)
        dirs = [
            p
            for p in Path(skills_dir).iterdir()
            if p.is_dir() and not p.name.startswith(".")
        ]
        # Only the single digest dir — the environment received exactly 1 skill
        assert len(dirs) == 1, f"expected exactly 1 mounted skill, got {dirs}"
        # Its SKILL.md carries the activated skill's body
        md = await box.files.read_text(f"{mounted}/SKILL.md")
        assert "body 42" in md


@pytest.mark.asyncio
async def test_lazy_mount_idempotent_same_digest(tmp_path):
    """同 digest 重复激活 → 复用已挂载路径，不重复拷贝。"""
    project = tmp_path / "proj"
    project.mkdir()
    skills_root = project / ".agents" / "skills"
    skills_root.mkdir(parents=True)
    make_skill_dirs(skills_root, 5)

    candidates = load_candidates(
        discover_candidate_sources(str(project), cwd=str(project), builtin_roots=())
    )
    catalog = build_catalog(
        candidates, generation=1, cwd=str(project), repo_root=str(project)
    )
    target = next(c for c in candidates if c.descriptor.name == "skill-000")
    store = PrivateSnapshotStore(tmp_path / "snapshots")

    async with await Sandbox.create(
        backend="local", workdir=str(tmp_path / "box")
    ) as box:
        mounter = LazySkillMounter(box, store=store)
        service = SkillActivationService(
            catalog, store=store, mounter=mounter, items_dir=tmp_path / "items"
        )
        request = ActivationRequest(
            request_id="req-1",
            thread_id="t1",
            run_id="run-1",
            skill_id=target.skill_id,
        )
        first = await service.activate(request)
        second = await service.activate(request)

        assert second.reused is True
        assert second.item.mounted_root == first.item.mounted_root
        skills_dir = box.resolve("/home/agent/.skills")
        dirs = [
            p
            for p in Path(skills_dir).iterdir()
            if p.is_dir() and not p.name.startswith(".")
        ]
        assert len(dirs) == 1


@pytest.mark.asyncio
async def test_lazy_mount_missing_snapshot_fails(tmp_path):
    """快照不存在时挂载失败 —— 不重新读取可能已改变的源文件。"""

    store = PrivateSnapshotStore(tmp_path / "snapshots")
    ref = store.save(name="skill-001", body="body 1\n")
    store.gc(set(), retention_days=0)  # simulate GC removing the snapshot
    assert store.path_for(ref) is None

    async with await Sandbox.create(
        backend="local", workdir=str(tmp_path / "box")
    ) as box:
        mounter = LazySkillMounter(box, store=store)
        with pytest.raises(FileNotFoundError, match="not found in private store"):
            await mounter.mount(ref)
        # Nothing left mounted
        skills_dir = box.resolve("/home/agent/.skills")
        dirs = (
            [p for p in Path(skills_dir).iterdir() if p.is_dir()]
            if _os.path.isdir(skills_dir)
            else []
        )
        assert len(dirs) == 0


@pytest.mark.asyncio
async def test_ssh_lazy_mount_verifies_digest(tmp_path):
    """SSH 懒挂载：staging 上传 + 原子 rename + digest 校验 + 缓存命中。"""
    from electromind.skills.mounting import SshLazySkillMounter

    store = PrivateSnapshotStore(tmp_path / "snapshots")
    ref = store.save(name="cp2k", body="SSH body\n")

    remote_root = tmp_path / "remote-home"
    sandbox = _FakeSshSandbox(remote_root)
    mounter = SshLazySkillMounter(sandbox, store=store)

    mounted = await mounter.mount(ref)
    assert mounted.startswith("/home/agent/.skills/")
    remote_md = Path(sandbox.resolve(f"{mounted}/SKILL.md"))
    assert remote_md.read_text(encoding="utf-8").strip() == "SSH body"
    assert any(c[0] == "mv" for c in sandbox.backend.exec_calls)

    # 同 digest 再次挂载 → 缓存命中，不重新上传
    exec_count = len(sandbox.backend.exec_calls)
    await mounter.mount(ref)
    assert len(sandbox.backend.exec_calls) == exec_count


@pytest.mark.asyncio
async def test_ssh_lazy_mount_digest_mismatch_rolls_back(tmp_path):
    """SSH 上传损坏 → digest 校验失败 → 回滚（无半挂载态）。"""
    from electromind.skills.mounting import SshLazySkillMounter

    store = PrivateSnapshotStore(tmp_path / "snapshots")
    ref = store.save(name="cp2k", body="GOOD body\n")

    remote_root = tmp_path / "remote-home"

    class _CorruptingBackend(_SshBackendBase):
        async def write_file(self, path, data):
            full = Path(path)
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_bytes(data[:5])  # 模拟上传损坏（截断）

    sandbox = _FakeSshSandbox(remote_root, backend=_CorruptingBackend())
    mounter = SshLazySkillMounter(sandbox, store=store)
    with pytest.raises(RuntimeError, match="digest mismatch"):
        await mounter.mount(ref)
    # 回滚：挂载目录已移除
    skills_dir = remote_root / ".skills"
    mounted_dirs = (
        [p for p in skills_dir.iterdir() if p.is_dir() and not p.name.startswith(".")]
        if skills_dir.exists()
        else []
    )
    assert mounted_dirs == []  # 无半挂载态（digest 目录已回滚）


class _CmdResult:
    def __init__(self, ok, stderr=""):
        self.ok = ok
        self.stderr = stderr


class _SshBackendBase:
    """用真实本地文件系统模拟 SSH 远端。"""

    def __init__(self):
        self.exec_calls: list[list[str]] = []

    async def exec(self, argv, **kwargs):
        self.exec_calls.append(argv)
        import subprocess

        r = subprocess.run(argv, capture_output=True, text=True)
        return _CmdResult(r.returncode == 0, r.stderr)

    async def write_file(self, path, data):
        full = Path(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(data)

    async def read_file(self, path):
        return Path(path).read_bytes()

    async def exists(self, path):
        return Path(path).exists()

    async def remove(self, path, *, recursive=False):
        import shutil

        p = Path(path)
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        else:
            p.unlink(missing_ok=True)


class _FakeSshSandbox:
    """虚拟 home → 远端根映射的假 Sandbox（files.write 走 sftp 语义）。"""

    home = "/home/agent"

    def __init__(self, remote_root: Path, backend=None):
        self.remote_root = remote_root
        self.workdir = str(remote_root)
        self.backend = backend or _SshBackendBase()
        self.files = _FakeSshFiles(self.backend, remote_root)

    def resolve(self, path):
        if path.startswith("/home/agent/"):
            rel = path[len("/home/agent/") :]
        else:
            rel = path.lstrip("/")
        # 虚拟 home 映射到远端根：/home/agent/.skills → <remote>/.skills
        return str(self.remote_root / rel)

    async def install_skill_snapshot(self, snapshot_dir, digest):
        """与真实 Sandbox 相同的 staging + 原子 rename + digest 缓存语义。"""
        dgst = digest[:8]
        target_dir = f"/home/agent/.skills/{dgst}"
        if await self.files.exists(target_dir):
            return target_dir
        staging = f"/home/agent/.skills/.staging/skill-{dgst}"
        src = Path(snapshot_dir)
        for dirpath, dirnames, filenames in _os.walk(src):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for filename in sorted(filenames):
                if filename.startswith("."):
                    continue
                full = Path(dirpath) / filename
                rel = full.relative_to(src).as_posix()
                await self.files.write(f"{staging}/{rel}", full.read_bytes())
        await self.backend.exec(["mv", self.resolve(staging), self.resolve(target_dir)])
        return target_dir


class _FakeSshFiles:
    def __init__(self, backend, root):
        self._backend = backend
        self._root = root

    def _map(self, path):
        if path.startswith("/home/agent/"):
            rel = path[len("/home/agent/") :]
        else:
            rel = path.lstrip("/")
        return str(self._root / rel)

    async def write(self, path, data, **_kw):
        await self._backend.write_file(self._map(path), data)

    async def read(self, path):
        return await self._backend.read_file(self._map(path))

    async def read_text(self, path):
        raw = await self._backend.read_file(self._map(path))
        return raw.decode("utf-8")

    async def exists(self, path):
        return await self._backend.exists(self._map(path))


@pytest.mark.asyncio
async def test_ssh_mount_resource_corruption_fails(tmp_path):
    """P1: SSH 校验覆盖 resources —— 资源损坏必须失败。"""
    from electromind.skills.mounting import SshLazySkillMounter

    store = PrivateSnapshotStore(tmp_path / "snapshots")
    # 带资源的快照
    skill_root = tmp_path / "skill-src"
    skill_root.mkdir()
    (skill_root / "SKILL.md").write_text(
        "---\nname: cp2k\ndescription: d\n---\nbody\n", encoding="utf-8"
    )
    res = skill_root / "resources"
    res.mkdir()
    (res / "data.txt").write_text("original config\n")
    ref = store.save(name="cp2k", body="body\n", resources_dir=skill_root)

    remote_root = tmp_path / "remote-home"

    class _CorruptResourcesBackend(_SshBackendBase):
        async def write_file(self, path, data):
            full = Path(path)
            full.parent.mkdir(parents=True, exist_ok=True)
            # 故意损坏资源文件（SKILL.md 正常）
            if full.name == "data.txt":
                full.write_bytes(b"BAD")
            else:
                full.write_bytes(data)

    sandbox = _FakeSshSandbox(remote_root, backend=_CorruptResourcesBackend())
    mounter = SshLazySkillMounter(sandbox, store=store)
    with pytest.raises(RuntimeError, match="digest mismatch on .*data.txt"):
        await mounter.mount(ref)
    # 回滚
    skills_dir = remote_root / ".skills"
    mounted = (
        [p for p in skills_dir.iterdir() if p.is_dir() and not p.name.startswith(".")]
        if skills_dir.exists()
        else []
    )
    assert mounted == []

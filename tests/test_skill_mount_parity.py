"""Mount parity: 同一激活快照在 local / container / ssh 三后端挂载后内容一致。

验收（v1.0 附件后端场景 + 复审）：
- local: 真实 Sandbox(backend="local")。
- ssh:   真实 loopback sshd（临时 host/client key + authorized_keys，
  asyncssh 连接）—— 不是本地文件系统 fake。
- container: 真实 docker/podman。环境缺失 → **fail**（复审：禁止用 skip
  绕过 MUST），不把实现错误吞成环境缺失。
- digest: store 快照 digest 与各后端挂载树的 sha256 完全相等（MOUNT round-trip）。

环境要求：/usr/sbin/sshd + ssh-keygen（loopback SSH）；docker 或 podman
（container）。不满足时测试失败并给出明确的环境说明。
"""

from __future__ import annotations

import getpass
import hashlib
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest

from electromind.skills.mounting import SshLazySkillMounter
from electromind.skills.snapstore import PrivateSnapshotStore, SkillSnapshotRef

SSHD = "/usr/sbin/sshd"


# ---------------------------------------------------------------------------
# loopback sshd fixture
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def loopback_ssh(tmp_path_factory):
    """启动一个真实 loopback sshd，返回连接参数。"""
    if not os.path.isfile(SSHD):
        pytest.fail(f"缺少 {SSHD} —— loopback SSH MUST 验收需要 sshd")
    if shutil.which("ssh-keygen") is None:
        pytest.fail("缺少 ssh-keygen —— loopback SSH MUST 验收需要 ssh-keygen")

    root = tmp_path_factory.mktemp("sshd")
    hostkey = root / "hostkey"
    clientkey = root / "clientkey"
    authorized = root / "authorized_keys"
    subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-f", str(hostkey), "-N", "", "-q"],
        check=True,
    )
    subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-f", str(clientkey), "-N", "", "-q"],
        check=True,
    )
    authorized.write_text((clientkey.with_suffix(".pub")).read_text() + "\n")

    port = _free_port()
    config = root / "sshd_config"
    config.write_text(
        "\n".join(
            [
                f"Port {port}",
                "ListenAddress 127.0.0.1",
                f"HostKey {hostkey}",
                f"AuthorizedKeysFile {authorized}",
                "PasswordAuthentication no",
                "PubkeyAuthentication yes",
                "StrictModes no",
                "UsePAM no",
                "Subsystem sftp /usr/libexec/sftp-server",
            ]
        )
        + "\n"
    )
    log = open(root / "sshd.log", "w")
    proc = subprocess.Popen(
        [SSHD, "-D", "-f", str(config), "-E", str(root / "sshd.err")],
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    # 等待端口就绪
    deadline = time.time() + 15
    ready = False
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                ready = True
                break
        except OSError:
            time.sleep(0.2)
    if not ready:
        err = (root / "sshd.err").read_text() if (root / "sshd.err").exists() else ""
        proc.terminate()
        pytest.fail(f"loopback sshd 未能启动: {err}")

    yield {
        "host": "127.0.0.1",
        "user": getpass.getuser(),
        "port": port,
        "client_keys": [str(clientkey)],
        "known_hosts": None,
    }
    proc.terminate()
    proc.wait(timeout=5)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _snapshot_tree(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }


def _tree_digest(tree: dict[str, bytes]) -> str:
    h = hashlib.sha256()
    for rel in sorted(tree):
        h.update(rel.encode())
        h.update(tree[rel])
    return h.hexdigest()


def _make_snapshot(store: PrivateSnapshotStore, tmp_path: Path) -> SkillSnapshotRef:
    return store.save(
        name="parity-skill",
        body="# Parity skill\nbody\n",
        resources=(
            ("run.sh", b"#!/bin/sh\necho parity\n"),
            ("references/running.md", b"# Running\n"),
        ),
    )


class TestMountParity:
    async def test_local_and_loopback_ssh_mounts_are_byte_identical(
        self, tmp_path, loopback_ssh
    ):
        """同一快照 local 与真 loopback SSH 挂载 → 内容树逐字节一致。"""

        from electromind.sandbox.sandbox import Sandbox

        store = PrivateSnapshotStore(tmp_path / "snapshots")
        ref = _make_snapshot(store, tmp_path)

        # local：真实本地 sandbox
        async with await Sandbox.create(
            backend="local", workdir=str(tmp_path / "box")
        ) as box:
            snapshot_dir = store.path_for(ref)
            assert snapshot_dir is not None
            mounted = await box.install_skill_snapshot(snapshot_dir, ref.digest)
            local_tree = _snapshot_tree(Path(box.resolve(mounted)))

        # ssh：真 loopback sshd（Sandbox.create 自动把 workdir 切到远端）
        remote_sandbox = await Sandbox.create(
            backend="ssh",
            workdir=str(tmp_path / "remote"),
            connection={**loopback_ssh, "workdir": str(tmp_path / "remote")},
        )
        try:
            mounter = SshLazySkillMounter(remote_sandbox, store=store)
            mounted_ssh = await mounter.mount(ref)
            ssh_tree = _snapshot_tree(Path(remote_sandbox.resolve(mounted_ssh)))
        finally:
            await remote_sandbox.close()

        assert local_tree, "local mount produced nothing"
        assert set(local_tree) == set(ssh_tree)
        for rel, data in local_tree.items():
            assert ssh_tree[rel] == data, f"parity mismatch: {rel}"

    async def test_loopback_ssh_mount_resources_preserved(self, tmp_path, loopback_ssh):
        """loopback SSH 挂载保留全部资源（references/** 与 scripts/**）。"""
        from electromind.sandbox.sandbox import Sandbox

        store = PrivateSnapshotStore(tmp_path / "snapshots")
        ref = _make_snapshot(store, tmp_path)
        remote_sandbox = await Sandbox.create(
            backend="ssh",
            workdir=str(tmp_path / "remote"),
            connection={**loopback_ssh, "workdir": str(tmp_path / "remote")},
        )
        try:
            mounter = SshLazySkillMounter(remote_sandbox, store=store)
            mounted = await mounter.mount(ref)
            tree = _snapshot_tree(Path(remote_sandbox.resolve(mounted)))
        finally:
            await remote_sandbox.close()
        assert tree["SKILL.md"].decode() == "# Parity skill\nbody\n"
        assert tree["resources/run.sh"] == b"#!/bin/sh\necho parity\n"
        assert tree["resources/references/running.md"] == b"# Running\n"

    async def test_digest_parity_store_local_ssh(self, tmp_path, loopback_ssh):
        """MOUNT round-trip：store 冻结内容与 local/SSH 挂载树的 digest 完全相等。"""
        from electromind.sandbox.sandbox import Sandbox

        store = PrivateSnapshotStore(tmp_path / "snapshots")
        ref = _make_snapshot(store, tmp_path)
        store_tree = _snapshot_tree(store.path_for(ref))
        store_digest = _tree_digest(store_tree)

        # local
        async with await Sandbox.create(
            backend="local", workdir=str(tmp_path / "box")
        ) as box:
            mounted = await box.install_skill_snapshot(store.path_for(ref), ref.digest)
            local_digest = _tree_digest(_snapshot_tree(Path(box.resolve(mounted))))

        # ssh
        remote_sandbox = await Sandbox.create(
            backend="ssh",
            workdir=str(tmp_path / "remote"),
            connection={**loopback_ssh, "workdir": str(tmp_path / "remote")},
        )
        try:
            mounter = SshLazySkillMounter(remote_sandbox, store=store)
            mounted_ssh = await mounter.mount(ref)
            ssh_digest = _tree_digest(
                _snapshot_tree(Path(remote_sandbox.resolve(mounted_ssh)))
            )
        finally:
            await remote_sandbox.close()

        assert local_digest == store_digest, "local 挂载树与 store 不一致"
        assert ssh_digest == store_digest, "SSH 挂载树与 store 不一致"

    async def test_container_mount_parity(self, tmp_path, monkeypatch):
        """container 后端真实挂载并比对。

        环境要求（复审）：ELECTROMIND_TEST_CONTAINER_IMAGE 指向本地预构建
        镜像（测试禁止自动 pull）；docker/podman daemon 必须可用；镜像必须
        已预加载。任一不满足 → fail（禁止 skip 绕过 MUST）。
        """
        import os

        from electromind.sandbox.sandbox import Sandbox

        image = os.environ.get("ELECTROMIND_TEST_CONTAINER_IMAGE")
        if not image:
            pytest.fail(
                "缺少 ELECTROMIND_TEST_CONTAINER_IMAGE —— container MUST 验收"
                "需要指定本地预构建镜像（CI 预加载，测试不自动 pull）"
            )

        cli = shutil.which("docker") or shutil.which("podman")
        if cli is None:
            pytest.fail("缺少 docker/podman CLI —— container MUST 验收需要容器 CLI")

        # daemon 可用性预检查
        daemon = subprocess.run(
            [cli, "info"], capture_output=True, text=True, timeout=30
        )
        if daemon.returncode != 0:
            pytest.fail(
                f"容器 daemon 不可用（{cli} info 失败）: {daemon.stderr.strip()[:200]}"
            )
        # 镜像已预加载预检查（不自动 pull）
        inspect = subprocess.run(
            [cli, "image", "inspect", image],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if inspect.returncode != 0:
            pytest.fail(
                f"测试镜像未预加载: {image} —— 请在 CI 预加载，测试禁止自动 pull"
            )

        store = PrivateSnapshotStore(tmp_path / "snapshots")
        ref = _make_snapshot(store, tmp_path)
        snapshot_dir = store.path_for(ref)
        assert snapshot_dir is not None
        try:
            async with await Sandbox.create(
                backend="container",
                workdir=str(tmp_path / "cbox"),
                image=image,
            ) as box:
                mounted = await box.install_skill_snapshot(snapshot_dir, ref.digest)
                tree = _snapshot_tree(Path(box.resolve(mounted)))
        except Exception as exc:  # noqa: BLE001 - 容器环境错误是真实失败
            pytest.fail(f"container 挂载失败（实现错误或环境问题）: {exc}")
        assert tree["SKILL.md"].decode() == "# Parity skill\nbody\n"
        assert tree["resources/run.sh"] == b"#!/bin/sh\necho parity\n"
        assert tree["resources/references/running.md"] == b"# Running\n"

"""SKILL-9 tests: user-invoked installer — local/archive/git, atomic, rollback."""

import shutil
import zipfile
from pathlib import Path

import pytest

from electromind.skills.installer import (
    InstallError,
    SkillInstaller,
    validate_skill_dir,
)


def _make_skill(root: Path, name: str, body: str = "body\n") -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: A test skill\n---\n{body}",
        encoding="utf-8",
    )
    (d / "run.sh").write_text("#!/bin/sh\necho hi\n")
    return d


class TestValidateSkillDir:
    def test_valid(self, tmp_path):
        d = _make_skill(tmp_path, "greet")
        assert validate_skill_dir(d) == "greet"

    def test_missing_skill_md(self, tmp_path):
        d = tmp_path / "nope"
        d.mkdir()
        with pytest.raises(InstallError, match="missing SKILL.md"):
            validate_skill_dir(d)

    def test_missing_description(self, tmp_path):
        d = tmp_path / "bad"
        d.mkdir()
        (d / "SKILL.md").write_text("---\nname: bad\n---\nbody\n", encoding="utf-8")
        with pytest.raises(InstallError, match="description"):
            validate_skill_dir(d)

    def test_invalid_name(self, tmp_path):
        d = tmp_path / "Bad Name"
        d.mkdir()
        (d / "SKILL.md").write_text(
            "---\nname: Bad Name\ndescription: d\n---\nb\n", encoding="utf-8"
        )
        with pytest.raises(InstallError, match="invalid skill name"):
            validate_skill_dir(d)


@pytest.mark.asyncio
class TestInstallFromDir:
    async def test_install_creates_skill(self, tmp_path):
        src = _make_skill(tmp_path / "src", "greet", "hi body\n")
        installer = SkillInstaller(tmp_path / "skills")
        result = await installer.install_from_dir(src)

        assert result.name == "greet"
        target = tmp_path / "skills" / "greet"
        assert (target / "SKILL.md").is_file()
        assert (target / "run.sh").is_file()
        assert result.record.source_type == "local"
        assert result.record.digest

    async def test_install_records_provenance(self, tmp_path):
        src = _make_skill(tmp_path / "src", "greet")
        installer = SkillInstaller(tmp_path / "skills")
        await installer.install_from_dir(src)

        records = installer.installed()
        assert len(records) == 1
        assert records[0].name == "greet"
        assert records[0].source == str(src)

    async def test_update_is_atomic_with_rollback(self, tmp_path):
        src = _make_skill(tmp_path / "src", "greet", "v1\n")
        installer = SkillInstaller(tmp_path / "skills")
        first = await installer.install_from_dir(src)
        assert first.updated is False

        # Update with new content → updated=True, previous_digest recorded
        (src / "SKILL.md").write_text(
            "---\nname: greet\ndescription: A test skill\n---\nv2\n",
            encoding="utf-8",
        )
        second = await installer.install_from_dir(src)
        assert second.updated is True
        assert second.record.previous_digest == first.record.digest
        assert (
            (tmp_path / "skills" / "greet" / "SKILL.md")
            .read_text(encoding="utf-8")
            .endswith("v2\n")
        )

    async def test_invalid_source_fails_cleanly(self, tmp_path):
        bad = tmp_path / "bad"
        bad.mkdir()
        (bad / "SKILL.md").write_text("---\nname: x\n---\nno desc\n", encoding="utf-8")
        installer = SkillInstaller(tmp_path / "skills")
        with pytest.raises(InstallError):
            await installer.install_from_dir(bad)
        # No partial install
        assert not (tmp_path / "skills").exists() or not list(
            (tmp_path / "skills").iterdir()
        )

    async def test_uninstall(self, tmp_path):
        src = _make_skill(tmp_path / "src", "greet")
        installer = SkillInstaller(tmp_path / "skills")
        await installer.install_from_dir(src)
        assert (tmp_path / "skills" / "greet").is_dir()

        assert await installer.uninstall("greet") is True
        assert not (tmp_path / "skills" / "greet").exists()
        assert await installer.uninstall("greet") is False  # already gone


@pytest.mark.asyncio
class TestInstallFromArchive:
    async def test_install_from_zip(self, tmp_path):
        src = _make_skill(tmp_path / "src", "greet")
        archive = tmp_path / "greet.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            for f in src.rglob("*"):
                if f.is_file():
                    zf.write(f, f.relative_to(tmp_path / "src").as_posix())

        installer = SkillInstaller(tmp_path / "skills")
        result = await installer.install_from_archive(archive)
        assert result.name == "greet"
        assert result.record.source_type == "archive"
        assert (tmp_path / "skills" / "greet" / "SKILL.md").is_file()

    async def test_archive_without_skill_fails(self, tmp_path):
        archive = tmp_path / "empty.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("README.txt", "no skills here")
        installer = SkillInstaller(tmp_path / "skills")
        with pytest.raises(InstallError, match="no SKILL.md"):
            await installer.install_from_archive(archive)

    async def test_unsupported_archive_fails(self, tmp_path):
        archive = tmp_path / "x.rar"
        archive.write_bytes(b"not really rar")
        installer = SkillInstaller(tmp_path / "skills")
        with pytest.raises(InstallError, match="unsupported archive"):
            await installer.install_from_archive(archive)


@pytest.mark.asyncio
class TestInstallFromGit:
    async def test_git_install(self, tmp_path):
        git = shutil.which("git")
        if git is None:
            pytest.skip("git not available")

        # Build a local git repo containing a skill
        repo = tmp_path / "repo"
        _make_skill(repo, "git-skill")
        import subprocess

        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.email", "t@t"], check=True
        )
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "skill"], check=True)

        installer = SkillInstaller(tmp_path / "skills")
        result = await installer.install_from_git(str(repo))
        assert result.name == "git-skill"
        assert result.record.source_type == "git"
        # SKILL-8: the install is pinned to the RESOLVED commit SHA, not #HEAD.
        assert result.record.resolved_commit
        assert result.record.source.endswith(f"#{result.record.resolved_commit}")
        assert (tmp_path / "skills" / "git-skill" / "SKILL.md").is_file()

    async def test_git_bad_repo_fails(self, tmp_path):
        installer = SkillInstaller(tmp_path / "skills")
        with pytest.raises(InstallError, match="git clone failed"):
            await installer.install_from_git("/nonexistent/repo-xyz")


class TestCliInstaller:
    """CLI 入口：install/uninstall/installed（用户显式调用）。"""

    def _run(self, argv, monkeypatch):
        import contextlib
        import io

        from app.commands import skills as skills_cmd

        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = skills_cmd.run(argv)
        return code, out.getvalue(), err.getvalue()

    def test_install_uninstall_roundtrip(self, tmp_path, monkeypatch):
        from app.exitcodes import EXIT_CLI, EXIT_OK

        src = _make_skill(tmp_path / "src", "cli-skill")
        # 隔离安装根（默认 ~/.electromind/skills 被 conftest HOME 隔离，但显式注入更稳）
        monkeypatch.setattr(
            "electromind.skills.installer.SkillInstaller.__init__",
            lambda self, root=None: setattr(self, "root", tmp_path / "skills"),
        )
        (tmp_path / "skills").mkdir(exist_ok=True)

        code, out, err = self._run(["install", "--dir", str(src)], monkeypatch)
        assert code == EXIT_OK, err
        assert "cli-skill" in out
        assert (tmp_path / "skills" / "cli-skill" / "SKILL.md").is_file()

        code, out, _ = self._run(["installed"], monkeypatch)
        assert code == EXIT_OK
        assert "cli-skill" in out
        assert "local" in out

        code, out, _ = self._run(["uninstall", "cli-skill"], monkeypatch)
        assert code == EXIT_OK
        assert not (tmp_path / "skills" / "cli-skill").exists()

        code, _, err = self._run(["uninstall", "cli-skill"], monkeypatch)
        assert code == EXIT_CLI

    def test_install_invalid_fails(self, tmp_path, monkeypatch):
        from app.exitcodes import EXIT_CLI

        bad = tmp_path / "bad"
        bad.mkdir()
        (bad / "SKILL.md").write_text("---\nname: x\n---\nno desc\n", encoding="utf-8")
        monkeypatch.setattr(
            "electromind.skills.installer.SkillInstaller.__init__",
            lambda self, root=None: setattr(self, "root", tmp_path / "skills"),
        )
        code, _out, err = self._run(["install", "--dir", str(bad)], monkeypatch)
        assert code == EXIT_CLI
        assert "安装失败" in err


class TestPathTraversalSecurity:
    """P0: 安装器不得逃逸安装根。"""

    async def test_uninstall_rejects_escape(self, tmp_path):
        installer = SkillInstaller(tmp_path / "skills")
        (tmp_path / "skills").mkdir()
        victim = tmp_path / "victim"
        victim.mkdir()
        (victim / "data.txt").write_text("keep me\n")

        with pytest.raises(InstallError, match="invalid skill name"):
            await installer.uninstall("../victim")
        assert (victim / "data.txt").is_file()  # 未删除

    async def test_uninstall_rejects_dotdot_with_valid_name(self, tmp_path):
        # 绕过 name 校验的路径形式（含 .. 但 name 部分合法）也被 containment 拒绝
        installer = SkillInstaller(tmp_path / "skills")
        (tmp_path / "skills").mkdir()
        victim = tmp_path / "victim"
        victim.mkdir()
        # name 校验先于 containment 拦截任何含路径分隔符的输入
        with pytest.raises(InstallError, match="invalid skill name"):
            await installer.uninstall("skills/../victim")

    async def test_tar_traversal_rejected(self, tmp_path):
        import tarfile

        archive = tmp_path / "evil.tar"
        with tarfile.open(archive, "w") as tf:
            data = b"escaped"
            info = tarfile.TarInfo("../escaped.txt")
            info.size = len(data)
            tf.addfile(info, __import__("io").BytesIO(data))

        installer = SkillInstaller(tmp_path / "skills")
        with pytest.raises(InstallError, match="escapes target"):
            await installer.install_from_archive(archive)
        assert not (tmp_path / "escaped.txt").exists()  # 未写出

    async def test_tar_absolute_path_rejected(self, tmp_path):
        import tarfile

        archive = tmp_path / "abs.tar"
        with tarfile.open(archive, "w") as tf:
            data = b"x"
            info = tarfile.TarInfo("/tmp/evil-skill.txt")
            info.size = len(data)
            tf.addfile(info, __import__("io").BytesIO(data))

        installer = SkillInstaller(tmp_path / "skills")
        with pytest.raises(InstallError, match="absolute path"):
            await installer.install_from_archive(archive)

    async def test_tar_gz_recognized(self, tmp_path):
        """.tar.gz 必须被识别（非 unsupported archive format）。"""
        import tarfile

        src = _make_skill(tmp_path / "src", "gz-skill")
        archive = tmp_path / "skill.tar.gz"
        with tarfile.open(archive, "w:gz") as tf:
            for f in src.rglob("*"):
                if f.is_file():
                    tf.add(f, arcname=f.relative_to(src).as_posix())

        installer = SkillInstaller(tmp_path / "skills")
        result = await installer.install_from_archive(archive)
        assert result.name == "gz-skill"
        assert (tmp_path / "skills" / "gz-skill" / "SKILL.md").is_file()

    async def test_zip_traversal_rejected(self, tmp_path):
        import zipfile

        archive = tmp_path / "evil.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../escaped.txt", "escaped")

        installer = SkillInstaller(tmp_path / "skills")
        with pytest.raises(InstallError, match="escapes target"):
            await installer.install_from_archive(archive)
        assert not (tmp_path / "escaped.txt").exists()


class TestTarSymlinkTraversal:
    """P0: tar symlink 组合穿越必须被拒绝。"""

    async def test_symlink_through_write_rejected(self, tmp_path):
        """link -> ../outside + link/pwn.txt 不得写出 staging 根目录。"""
        import io
        import tarfile

        archive = tmp_path / "symlink-evil.tar"
        with tarfile.open(archive, "w") as tf:
            # 1. 符号链接成员：指向 staging 根之外
            link = tarfile.TarInfo("link")
            link.type = tarfile.SYMTYPE
            link.linkname = "../outside"
            tf.addfile(link)
            # 2. 通过符号链接写入的文件
            data = b"owned"
            pwn = tarfile.TarInfo("link/pwn.txt")
            pwn.size = len(data)
            tf.addfile(pwn, io.BytesIO(data))

        installer = SkillInstaller(tmp_path / "skills")
        with pytest.raises(InstallError, match="link/special file"):
            await installer.install_from_archive(archive)
        # 不得在 staging 根外生成文件
        assert not (tmp_path / "outside" / "pwn.txt").exists()
        assert not (tmp_path / "pwn.txt").exists()

    async def test_hardlink_rejected(self, tmp_path):
        import io
        import tarfile

        archive = tmp_path / "hardlink.tar"
        with tarfile.open(archive, "w") as tf:
            data = b"x"
            regular = tarfile.TarInfo("a.txt")
            regular.size = len(data)
            tf.addfile(regular, io.BytesIO(data))
            hard = tarfile.TarInfo("b.txt")
            hard.type = tarfile.LNKTYPE
            hard.linkname = "a.txt"
            tf.addfile(hard)

        installer = SkillInstaller(tmp_path / "skills")
        with pytest.raises(InstallError, match="link/special file"):
            await installer.install_from_archive(archive)

    async def test_absolute_link_target_rejected(self, tmp_path):
        import tarfile

        archive = tmp_path / "abslink.tar"
        with tarfile.open(archive, "w") as tf:
            link = tarfile.TarInfo("evil")
            link.type = tarfile.SYMTYPE
            link.linkname = "/etc/passwd"
            tf.addfile(link)

        installer = SkillInstaller(tmp_path / "skills")
        with pytest.raises(InstallError, match="link/special file"):
            await installer.install_from_archive(archive)

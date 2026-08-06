"""P1.5: 数据完整性诊断（data doctor）。"""

from __future__ import annotations

import json
from pathlib import Path

from app.commands.data_doctor import check_single_thread, collect_data_checks
from electromind.atomicfile import atomic_write_text


def _make_thread(home: Path, thread_id: str) -> Path:
    d = home / "threads" / thread_id
    d.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        d / "thread.toml",
        '[agent]\nname = "main"\n[project]\npath = "/tmp"\n',
        backup=True,
    )
    atomic_write_text(d / "metainfo.json", json.dumps({"title": "t"}), backup=True)
    return d


def test_healthy_thread_passes(tmp_path):
    d = _make_thread(tmp_path, "thread-1")
    check = check_single_thread(d, tmp_path)
    assert check.ok, check.issues
    assert check.issues == []


def test_corrupt_thread_toml_with_no_backup_detected(tmp_path):
    d = _make_thread(tmp_path, "thread-2")
    (d / "thread.toml").write_text("[[[[ not toml", encoding="utf-8")
    # 无 .bak → load_toml_recover 返回 None → 报损坏
    (d / "thread.toml.bak").unlink(missing_ok=True)
    check = check_single_thread(d, tmp_path)
    assert not check.ok
    assert any("thread.toml" in i for i in check.issues)


def test_corrupt_thread_toml_recovered_from_backup(tmp_path):
    d = _make_thread(tmp_path, "thread-2b")
    (d / "thread.toml").write_text("[[[[ not toml", encoding="utf-8")
    # .bak 存在且可解析 → load_toml_recover 从 .bak 恢复 → 结构完整不算失败
    (d / "thread.toml.bak").write_text(
        '[agent]\nname = "backup"\n[project]\npath = "/tmp"\n',
        encoding="utf-8",
    )
    check = check_single_thread(d, tmp_path)
    assert check.ok, check.issues


def test_corrupt_metainfo_detected(tmp_path):
    d = _make_thread(tmp_path, "thread-3")
    (d / "metainfo.json").write_text("{ bad json", encoding="utf-8")
    check = check_single_thread(d, tmp_path)
    assert not check.ok
    assert any("metainfo.json" in i for i in check.issues)


def test_missing_thread_toml_detected(tmp_path):
    d = tmp_path / "threads" / "thread-4"
    d.mkdir(parents=True)
    check = check_single_thread(d, tmp_path)
    assert not check.ok
    assert any("thread.toml" in i for i in check.issues)


def test_artifact_sha_mismatch_detected(tmp_path):
    d = _make_thread(tmp_path, "thread-5")
    from electromind.artifacts import ArtifactManifest, ArtifactRegistry

    f = d / "energy.json"
    f.write_text('{"e": -76.4}', encoding="utf-8")
    registry = ArtifactRegistry(d / "artifacts.jsonl")
    registry.register(
        ArtifactManifest(
            artifact_id="energy.json",
            type="parsed_result",
            path="energy.json",
            sha256="deadbeef",  # 错误的 SHA
        )
    )
    check = check_single_thread(d, tmp_path)
    assert not check.ok
    assert any("Artifact" in i for i in check.issues)


def test_artifact_sha_match_passes(tmp_path):
    d = _make_thread(tmp_path, "thread-6")
    from electromind.artifacts import ArtifactManifest, ArtifactRegistry, sha256_file

    f = d / "energy.json"
    f.write_text('{"e": -76.4}', encoding="utf-8")
    registry = ArtifactRegistry(d / "artifacts.jsonl")
    registry.register(
        ArtifactManifest(
            artifact_id="energy.json",
            type="parsed_result",
            path="energy.json",
            sha256=sha256_file(f),
        )
    )
    check = check_single_thread(d, tmp_path)
    assert check.ok, check.issues


def test_corrupt_messages_detected(tmp_path):
    d = _make_thread(tmp_path, "thread-7")
    (d / "messages").mkdir(exist_ok=True)
    (d / "messages" / "messages.jsonl").write_text(
        '{"role": "user", "content": [{"type": "text", "text": "hi"}]}\n'
        "NOT_A_MESSAGE\n"
        '{"role": "assistant", "content": [{"type": "text", "text": "ok"}]}\n',
        encoding="utf-8",
    )
    check = check_single_thread(d, tmp_path)
    assert not check.ok
    assert any("messages.jsonl" in i for i in check.issues)


def test_disk_space_low_detected(tmp_path, monkeypatch):
    d = _make_thread(tmp_path, "thread-disk")
    check = check_single_thread(d, tmp_path)
    assert check.ok, check.issues  # 正常环境磁盘充足

    import app.commands.data_doctor as dd

    monkeypatch.setattr(
        dd.shutil,
        "disk_usage",
        lambda _p: type("U", (), {"free": 512 * 1024 * 1024})(),  # 0.5GB
    )
    check2 = check_single_thread(d, tmp_path)
    assert not check2.ok
    assert any("磁盘剩余空间" in i for i in check2.issues)


def test_collect_data_checks_scans_threads(tmp_path, monkeypatch):
    # 用临时 home 隔离，避免扫到真实用户数据（collect_data_checks 在函数体内
    # 从 electromind.paths 导入 default_electromind_home，故 patch 那里）。
    monkeypatch.setattr("electromind.paths.default_electromind_home", lambda: tmp_path)
    _make_thread(tmp_path, "thread-ok")
    _make_thread(tmp_path, "thread-bad")
    (tmp_path / "threads" / "thread-bad" / "metainfo.json").write_text(
        "{ bad", encoding="utf-8"
    )
    checks = collect_data_checks()
    assert {c.thread_id for c in checks} == {"thread-bad", "thread-ok"}
    bad = {c.thread_id for c in checks if not c.ok}
    assert bad == {"thread-bad"}

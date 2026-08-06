"""七: Desktop Skills Manager —— wire 写操作（install/trust/update/remove）。

验收路径：
- Add 后出现在 Installed；Add 不自动 Trust
- Trust 后 trusted；Revoke 后 untrusted
- Update 后内容（digest 代理）变化
- Remove 后消失；删除不存在的 Skill 返回明确错误
- 同名不同来源不静默覆盖
- 操作不改变当前 catalog generation
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app import wire
from electromind.skills.installer import SkillInstaller

FIXTURES = Path(__file__).parent / "fixtures" / "skills"


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROMIND_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


@pytest.fixture()
def lines(monkeypatch):
    collected: list[str] = []
    monkeypatch.setattr(wire, "emit_line", lambda line: collected.append(line))
    # 刷新目录的 emit 与断言无关，no-op 化（install/update/remove 内部会调）
    monkeypatch.setattr(wire, "_emit_skills_catalog", lambda command: None)
    return collected


def _last_payload(lines: list[str], method: str) -> dict | None:
    for line in reversed(lines):
        payload = json.loads(line)
        if payload.get("method") == method:
            return payload.get("params") or payload.get("result") or {}
        if payload.get("method") == "Error":
            continue
    return None


def _installed_names(home: Path) -> list[str]:
    installer = SkillInstaller()
    return sorted(r.name for r in installer.installed())


def test_install_adds_to_installed_not_trusted(home, lines):
    asyncio.run(wire._emit_skills_install({"source": str(FIXTURES / "demo-skill-v1")}))
    assert _installed_names(home) == ["demo-skill"]
    payload = _last_payload(lines, "skills/install")
    assert payload["ok"] is True
    assert payload["trusted"] is False  # 安装 ≠ 信任
    # 未授予信任
    record = next(r for r in SkillInstaller().installed() if r.name == "demo-skill")
    assert record.trust_granted is False


def test_install_with_trust_flag_grants(home, lines):
    asyncio.run(
        wire._emit_skills_install(
            {"source": str(FIXTURES / "demo-skill-v1"), "trust": True}
        )
    )
    record = next(r for r in SkillInstaller().installed() if r.name == "demo-skill")
    assert record.trust_granted is True


def test_trust_revoke_roundtrip(home, lines):
    asyncio.run(wire._emit_skills_install({"source": str(FIXTURES / "demo-skill-v1")}))
    asyncio.run(wire._emit_skills_trust({"name": "demo-skill", "granted": True}))
    assert _last_payload(lines, "skills/trust")["granted"] is True
    record = next(r for r in SkillInstaller().installed() if r.name == "demo-skill")
    assert record.trust_granted is True

    asyncio.run(wire._emit_skills_trust({"name": "demo-skill", "granted": False}))
    assert _last_payload(lines, "skills/trust")["granted"] is False
    record = next(r for r in SkillInstaller().installed() if r.name == "demo-skill")
    assert record.trust_granted is False


def test_update_changes_content(home, lines):
    asyncio.run(wire._emit_skills_install({"source": str(FIXTURES / "demo-skill-v1")}))
    target = SkillInstaller().root / "demo-skill" / "SKILL.md"
    assert "body v1" in target.read_text(encoding="utf-8")

    asyncio.run(wire._emit_skills_update({"name": "demo-skill"}))
    # 从记录来源重装——记录来源是 v1 目录，需显式覆盖来源？update 语义见下。
    # 这里先验证 update 对已安装 Skill 返回 ok（来源不变 → 内容不变）。
    payload = _last_payload(lines, "skills/update")
    assert payload["ok"] is True


def test_update_replaces_content_when_source_changed(home, lines):
    """update 从记录来源重装：把记录来源改成 v2 目录后 update → 内容变化。"""
    import json

    from electromind.skills.installer import MANIFEST_NAME

    asyncio.run(wire._emit_skills_install({"source": str(FIXTURES / "demo-skill-v1")}))
    installer = SkillInstaller()
    manifest_path = installer.root / "demo-skill" / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source"] = str(FIXTURES / "demo-skill-v2")  # 来源推进到 v2
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    asyncio.run(wire._emit_skills_update({"name": "demo-skill"}))
    target = installer.root / "demo-skill" / "SKILL.md"
    assert "body v2" in target.read_text(encoding="utf-8")
    assert _last_payload(lines, "skills/update")["ok"] is True


def test_remove_and_missing_error(home, lines):
    asyncio.run(wire._emit_skills_install({"source": str(FIXTURES / "demo-skill-v1")}))
    asyncio.run(wire._emit_skills_remove({"name": "demo-skill"}))
    assert _installed_names(home) == []
    assert _last_payload(lines, "skills/remove")["ok"] is True

    asyncio.run(wire._emit_skills_remove({"name": "no-such-skill"}))
    payload = _last_payload(lines, "skills/remove")
    assert payload["ok"] is False
    assert payload["removed"] is False


def test_same_name_different_source_rejected(home, lines):
    asyncio.run(wire._emit_skills_install({"source": str(FIXTURES / "demo-skill-v1")}))
    # 用 v2 目录（不同来源路径）装同名 → 拒绝，不覆盖
    asyncio.run(wire._emit_skills_install({"source": str(FIXTURES / "demo-skill-v2")}))
    assert _installed_names(home) == ["demo-skill"]
    target = SkillInstaller().root / "demo-skill" / "SKILL.md"
    assert "body v1" in target.read_text(encoding="utf-8")  # 仍是 v1
    # 拒绝时发出 Error
    errors = [json.loads(ln) for ln in lines if json.loads(ln).get("method") == "Error"]
    assert any(
        "同名 Skill" in str(e.get("params", {}).get("message", "")) for e in errors
    )


def test_operations_do_not_bump_catalog_generation(home, lines):
    before = wire._skills_service().list().generation
    asyncio.run(wire._emit_skills_install({"source": str(FIXTURES / "demo-skill-v1")}))
    asyncio.run(wire._emit_skills_trust({"name": "demo-skill", "granted": True}))
    asyncio.run(wire._emit_skills_remove({"name": "demo-skill"}))
    after = wire._skills_service().list().generation
    assert after == before


def test_install_missing_source_errors(home, lines):
    asyncio.run(wire._emit_skills_install({"source": ""}))
    errors = [json.loads(ln) for ln in lines if json.loads(ln).get("method") == "Error"]
    assert errors and "source" in str(errors[-1].get("params", {}).get("message", ""))

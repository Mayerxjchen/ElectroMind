"""P4: /skill 调用 wire 测试 —— invocation 字段 + skills/activated 广播。"""

from __future__ import annotations

import json
from types import SimpleNamespace

from app import wire


def _capture(monkeypatch) -> list[str]:
    lines: list[str] = []
    monkeypatch.setattr(wire, "emit_line", lambda line: lines.append(line))
    return lines


def _fake_catalog(disable_model_invocation: bool = False):
    return SimpleNamespace(
        generation=1,
        catalog_digest="digest-1",
        cwd="",
        repo_root="",
        source_fingerprints={},
        resolution={},
        candidates=[
            SimpleNamespace(
                skill_id="builtin:cp2k",
                descriptor=SimpleNamespace(
                    name="cp2k",
                    description="CP2K",
                    disable_model_invocation=disable_model_invocation,
                    content_digest="abc123",
                ),
                source=SimpleNamespace(
                    scope="builtin", dialect="", source_id="builtin"
                ),
                enabled_state="enabled",
                trust_state="trusted",
            )
        ],
    )


def test_catalog_payload_invocation_both(monkeypatch):
    payload = wire._skills_catalog_payload(
        _fake_catalog(disable_model_invocation=False)
    )
    assert payload["skills"][0]["invocation"] == "both"


def test_catalog_payload_invocation_manual(monkeypatch):
    """disable-model-invocation 的 Skill（hpc-submit 等）→ manual。"""
    payload = wire._skills_catalog_payload(_fake_catalog(disable_model_invocation=True))
    assert payload["skills"][0]["invocation"] == "manual"


async def test_activate_skill_for_run_no_catalog_emits_failure(monkeypatch):
    """无 Skill catalog 时广播 skills/activated ok=false，不阻断。"""
    lines = _capture(monkeypatch)
    runner = SimpleNamespace(skill_runtime=None)
    ok = await wire._activate_skill_for_run(runner, "cp2k", "t1")
    assert ok is False
    captured = [json.loads(line) for line in lines]
    assert captured[0]["method"] == "skills/activated"
    assert captured[0]["params"]["name"] == "cp2k"
    assert captured[0]["params"]["ok"] is False


def _real_catalog(tmp_path) -> "object":
    """真实 MultiCandidateCatalog（可信 cp2k 候选，真实 SKILL.md 冻结正文）。"""
    from pathlib import Path

    from electromind.skills.candidate import (
        SkillCandidate,
        SkillDescriptor,
        SkillSource,
        make_skill_id,
    )
    from electromind.skills.catalog import build_catalog

    root = Path(tmp_path) / "cp2k"
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(
        "---\nname: cp2k\ndescription: CP2K\n---\n\nActivate the `cp2k` skill.\n",
        encoding="utf-8",
    )
    source = SkillSource(
        source_id="builtin-cp2k",
        scope="builtin",  # type: ignore[arg-type]
        dialect="agents",
        root=root,
        project_root=None,
        distance_from_cwd=None,
        trust_domain="builtin",
    )
    skill_id = make_skill_id(
        scope="builtin", name="cp2k", dialect="agents", project_dir=None
    )
    descriptor = SkillDescriptor(
        name="cp2k",
        description="CP2K",
        entry_path=root / "SKILL.md",
        root_path=root,
        frontmatter={"name": "cp2k", "description": "CP2K"},
        content_digest="abc123",
        resource_digest="r1",
    )
    candidate = SkillCandidate(
        skill_id=skill_id,
        descriptor=descriptor,
        source=source,
        enabled_state="on",
        trust_state="trusted",
    )
    return build_catalog([candidate], generation=1, cwd="/w", repo_root="/r")


async def test_activate_skill_for_run_unresolved_emits_failure(monkeypatch, tmp_path):
    """Skill 不可解析（不存在）→ 广播失败，不注入上下文。"""
    lines = _capture(monkeypatch)
    catalog = _real_catalog(tmp_path)
    skill_runtime = SimpleNamespace(
        _current_view=SimpleNamespace(catalog=catalog),
        capabilities=(),
        mounter=None,
    )
    runner = SimpleNamespace(
        skill_runtime=skill_runtime, agent=SimpleNamespace(system="sys")
    )
    ok = await wire._activate_skill_for_run(runner, "no-such-skill", "t1")
    assert ok is False
    captured = [json.loads(line) for line in lines]
    assert captured[0]["params"]["ok"] is False
    # 未注入任何上下文
    assert runner.agent.system == "sys"


async def test_activate_skill_for_run_success_injects_and_broadcasts(
    monkeypatch, tmp_path
):
    """可信 Skill 解析成功 → payload 注入 agent 系统提示 + 广播成功。"""
    lines = _capture(monkeypatch)
    catalog = _real_catalog(tmp_path)
    skill_runtime = SimpleNamespace(
        _current_view=SimpleNamespace(catalog=catalog),
        capabilities=(),
        mounter=None,
    )
    runner = SimpleNamespace(
        skill_runtime=skill_runtime, agent=SimpleNamespace(system="sys")
    )
    ok = await wire._activate_skill_for_run(runner, "cp2k", "t1")
    assert ok is True
    captured = [json.loads(line) for line in lines]
    params = captured[0]["params"]
    assert params["name"] == "cp2k"
    assert params["ok"] is True
    assert params["source"] == "builtin-cp2k"
    assert params["digest"] == "abc123"
    # payload 已前置注入系统提示
    assert runner.agent.system.startswith("{") and runner.agent.system.endswith("sys")


def test_emit_skills_catalog_reloads_fresh_not_cached(monkeypatch):
    """``skills/list`` 用 reload()（重扫）而非 list()（缓存）。

    list() 首次加载后返回缓存，install/update/remove/trust 等变更后再
    吐的目录仍是旧的（面板残留已删 Skill）。reload() 做指纹检测，
    磁盘变化时重新扫描。这里用 stub 证明 emit 的是 reload() 的产物。
    """
    lines = _capture(monkeypatch)

    class _StubService:
        def list(self):
            # 缓存视图：仍含 cp2k（旧目录）
            return _fake_catalog()

        def reload(self):
            # 重扫视图：cp2k 已被移除
            return SimpleNamespace(
                generation=2,
                catalog_digest="digest-2",
                cwd="",
                repo_root="",
                source_fingerprints={},
                resolution={},
                candidates=[],
            )

    monkeypatch.setattr(wire, "_skills_service", lambda: _StubService())
    wire._emit_skills_catalog({"thread_id": ""})
    payload = json.loads(lines[-1])
    assert payload["method"] == "skills/list"
    assert payload["params"]["skills"] == []

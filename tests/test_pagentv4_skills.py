import json
import os
from pathlib import Path

import pytest

from pagentv4 import (
    Skill,
    SkillDiscoveryError,
    SkillRegistry,
    build_skills_system_prompt,
    default_skill_roots,
    load_skill,
    load_skills_from_root,
    make_use_skill_tool,
)
from pagentv4.skills.skill import (
    PROJECT_LOCAL_SKILLS_DIR,
    SKILLS_ENV_VAR,
    USER_SKILLS_DIR,
    collect_resources,
    parse_skill_md,
)


def write_skill_dir(root: Path, name: str, description: str, body: str) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    text = f"---\nname: {name}\ndescription: {description}\n---\n{body}"
    (d / "SKILL.md").write_text(text, encoding="utf-8")
    return d


def test_parse_skill_md_with_frontmatter():
    text = (
        "---\n"
        "name: greet\n"
        "description: 打招呼\n"
        "# 这是注释\n"
        'extra: "quoted value"\n'
        "---\n"
        "正文第一行\n正文第二行\n"
    )
    fm, body = parse_skill_md(text)
    assert fm == {
        "name": "greet",
        "description": "打招呼",
        "extra": "quoted value",
    }
    assert body == "正文第一行\n正文第二行\n"


def test_parse_skill_md_without_frontmatter():
    fm, body = parse_skill_md("no frontmatter here\n")
    assert fm == {}
    assert body == "no frontmatter here\n"


def test_parse_skill_md_strips_bom():
    fm, body = parse_skill_md("\ufeff---\ndescription: x\n---\nbody\n")
    assert fm == {"description": "x"}
    assert body == "body\n"


def test_load_skill_reads_body_and_resources(tmp_path):
    skill_dir = write_skill_dir(tmp_path, "reporter", "生成报告", "步骤如下\n")
    (skill_dir / "scripts").mkdir()
    (skill_dir / "scripts" / "run.sh").write_text("#!/bin/sh\necho hi\n")
    (skill_dir / ".hidden").write_text("nope")
    (skill_dir / ".secret_dir").mkdir()
    (skill_dir / ".secret_dir" / "x").write_text("nope")

    skill = load_skill(skill_dir)
    assert skill.name == "reporter"
    assert skill.description == "生成报告"
    assert skill.instructions == "步骤如下"
    assert skill.root == skill_dir.resolve()
    assert skill.resources == ("scripts/run.sh",)


def test_load_skill_falls_back_to_dir_name_when_name_missing(tmp_path):
    d = tmp_path / "auto-name"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\ndescription: 无 name\n---\nbody\n", encoding="utf-8"
    )
    skill = load_skill(d)
    assert skill.name == "auto-name"


def test_load_skill_requires_description(tmp_path):
    d = tmp_path / "broken"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: broken\n---\nbody\n", encoding="utf-8")
    with pytest.raises(SkillDiscoveryError):
        load_skill(d)


def test_load_skill_requires_skill_md(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    with pytest.raises(SkillDiscoveryError):
        load_skill(d)


def test_collect_resources_ignores_dot_and_skill_md(tmp_path):
    write_skill_dir(tmp_path, "s", "d", "body\n")
    (tmp_path / "s" / "a.txt").write_text("x")
    (tmp_path / "s" / "nested").mkdir()
    (tmp_path / "s" / "nested" / "b.md").write_text("y")
    (tmp_path / "s" / ".git").mkdir()
    (tmp_path / "s" / ".git" / "HEAD").write_text("nope")

    resources = collect_resources((tmp_path / "s").resolve())
    assert resources == ["a.txt", "nested/b.md"]


def test_load_skills_from_root_scans_children(tmp_path):
    write_skill_dir(tmp_path, "alpha", "第一份", "aa\n")
    write_skill_dir(tmp_path, "beta", "第二份", "bb\n")
    (tmp_path / "not-a-skill").mkdir()

    skills = load_skills_from_root(tmp_path)
    assert [s.name for s in skills] == ["alpha", "beta"]


def test_load_skills_from_root_missing_returns_empty(tmp_path):
    assert load_skills_from_root(tmp_path / "does-not-exist") == []


def test_registry_register_and_lookup(tmp_path):
    write_skill_dir(tmp_path, "alpha", "第一份", "aa\n")
    write_skill_dir(tmp_path, "beta", "第二份", "bb\n")

    registry = SkillRegistry.from_dirs(tmp_path)
    assert registry.names() == ["alpha", "beta"]
    assert registry.get("alpha").description == "第一份"
    assert registry.get("missing") is None


def test_registry_rejects_duplicate():
    skill = Skill(
        name="dup",
        description="d",
        instructions="",
        root=Path("/tmp/dup"),
    )
    registry = SkillRegistry([skill])
    with pytest.raises(ValueError):
        registry.register(skill)


def test_registry_summary_empty_returns_empty_string():
    assert SkillRegistry().summary() == ""
    assert build_skills_system_prompt(SkillRegistry()) == ""


def test_registry_summary_lists_names_and_descriptions(tmp_path):
    write_skill_dir(tmp_path, "alpha", "第一份", "aa\n")
    write_skill_dir(tmp_path, "beta", "第二份", "bb\n")
    registry = SkillRegistry.from_dirs(tmp_path)

    summary = registry.summary()
    assert "alpha" in summary and "第一份" in summary
    assert "beta" in summary and "第二份" in summary
    assert "use_skill" in summary


@pytest.mark.asyncio
async def test_use_skill_tool_returns_full_payload(tmp_path):
    write_skill_dir(tmp_path, "alpha", "第一份", "步骤 A\n")
    (tmp_path / "alpha" / "run.sh").write_text("echo hi\n")
    registry = SkillRegistry.from_dirs(tmp_path)
    tool = make_use_skill_tool(registry)

    result = await tool.acall({"name": "alpha"})
    assert result.ok is True
    payload = json.loads(result.content)
    assert payload["ok"] is True
    assert payload["name"] == "alpha"
    assert payload["description"] == "第一份"
    assert payload["instructions"] == "步骤 A"
    assert payload["resources"] == ["run.sh"]
    assert payload["root"].endswith("alpha")


@pytest.mark.asyncio
async def test_use_skill_tool_unknown_name_lists_available(tmp_path):
    write_skill_dir(tmp_path, "alpha", "第一份", "aa\n")
    registry = SkillRegistry.from_dirs(tmp_path)
    tool = make_use_skill_tool(registry)

    result = await tool.acall({"name": "ghost"})
    payload = json.loads(result.content)
    assert payload["ok"] is False
    assert "ghost" in payload["error"]
    assert payload["available"] == ["alpha"]


def test_use_skill_tool_description_mentions_available_names(tmp_path):
    write_skill_dir(tmp_path, "alpha", "第一份", "aa\n")
    registry = SkillRegistry.from_dirs(tmp_path)
    tool = make_use_skill_tool(registry)
    assert "alpha" in tool.description


def test_use_skill_tool_description_when_empty():
    tool = make_use_skill_tool(SkillRegistry())
    assert "暂无可用 skill" in tool.description


def test_default_skill_roots_no_env(monkeypatch, tmp_path):
    monkeypatch.delenv(SKILLS_ENV_VAR, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    roots = default_skill_roots()
    assert roots == [
        tmp_path / PROJECT_LOCAL_SKILLS_DIR,
        Path(USER_SKILLS_DIR).expanduser(),
    ]


def test_default_skill_roots_env_prepends_paths(monkeypatch, tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    monkeypatch.setenv(SKILLS_ENV_VAR, os.pathsep.join([str(a), str(b)]))
    monkeypatch.chdir(tmp_path)

    roots = default_skill_roots()
    assert roots[0] == a
    assert roots[1] == b
    assert tmp_path / PROJECT_LOCAL_SKILLS_DIR in roots


def test_default_skill_roots_env_ignores_empty_parts(monkeypatch, tmp_path):
    monkeypatch.setenv(SKILLS_ENV_VAR, os.pathsep + "  " + os.pathsep)
    monkeypatch.chdir(tmp_path)
    roots = default_skill_roots()
    # 空段被跳过，只剩项目本地 + 用户级
    assert all(str(r) for r in roots)
    assert len(roots) == 2


def test_registry_from_defaults_reads_env_dir(monkeypatch, tmp_path):
    env_dir = tmp_path / "shared_skills"
    env_dir.mkdir()
    write_skill_dir(env_dir, "shared", "共享 skill", "body\n")
    monkeypatch.setenv(SKILLS_ENV_VAR, str(env_dir))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    registry = SkillRegistry.from_defaults()
    assert "shared" in registry.names()


def test_registry_from_defaults_accepts_extra_roots(monkeypatch, tmp_path):
    monkeypatch.delenv(SKILLS_ENV_VAR, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    extra = tmp_path / "extra"
    extra.mkdir()
    write_skill_dir(extra, "explicit", "显式传入", "body\n")

    registry = SkillRegistry.from_defaults(extra)
    assert "explicit" in registry.names()


def test_registry_from_defaults_missing_dirs_are_ignored(monkeypatch, tmp_path):
    monkeypatch.delenv(SKILLS_ENV_VAR, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    # 默认路径都不存在，注册表也应能构造出来，不抛错
    registry = SkillRegistry.from_defaults()
    assert registry.names() == []


def test_summary_with_mount_shows_agent_paths(tmp_path):
    write_skill_dir(tmp_path, "alpha", "第一份", "aa\n")
    registry = SkillRegistry.from_dirs(tmp_path)
    summary = registry.summary(mount={"alpha": "/home/agent/.skills/alpha"})
    assert "/home/agent/.skills/alpha" in summary
    assert "你自己电脑" in summary


@pytest.mark.asyncio
async def test_use_skill_tool_uses_mount_for_root(tmp_path):
    write_skill_dir(tmp_path, "alpha", "第一份", "aa\n")
    registry = SkillRegistry.from_dirs(tmp_path)
    tool = make_use_skill_tool(
        registry,
        mount={"alpha": "/home/agent/.skills/alpha"},
    )

    result = await tool.acall({"name": "alpha"})
    payload = json.loads(result.content)
    assert payload["root"] == "/home/agent/.skills/alpha"
    assert "你电脑上的路径" in tool.description


@pytest.mark.asyncio
async def test_use_skill_tool_falls_back_to_host_root_without_mount(tmp_path):
    write_skill_dir(tmp_path, "alpha", "第一份", "aa\n")
    registry = SkillRegistry.from_dirs(tmp_path)
    tool = make_use_skill_tool(registry)

    result = await tool.acall({"name": "alpha"})
    payload = json.loads(result.content)
    # 没传 mount 时回退到宿主机 skill 根目录
    assert payload["root"].endswith("alpha")

import json
from pathlib import Path

import pytest

from electromind import (
    Skill,
    SkillDiscoveryError,
    SkillRegistry,
    build_skills_system_prompt,
    default_skill_roots,
    load_skill,
    load_skills_from_root,
    make_use_skill_tool,
)
from electromind.skills.discovery import (
    SkillMount,
    discover_skill_sources,
    load_skill_catalog,
)
from electromind.skills.skill import (
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


def test_parse_skill_md_folded_block_scalar_joins_lines():
    text = (
        "---\n"
        "name: packer\n"
        "description: >\n"
        "  Use when the user needs to pack molecules\n"
        "  into an initial box.\n"
        "always: false\n"
        "---\n"
        "body\n"
    )
    fm, body = parse_skill_md(text)
    assert fm["name"] == "packer"
    assert fm["description"] == (
        "Use when the user needs to pack molecules into an initial box.\n"
    )
    assert fm["always"] is False
    assert body == "body\n"


def test_parse_skill_md_literal_block_scalar_keeps_newlines():
    text = "---\ndescription: |\n  line one\n  line two\n---\nbody\n"
    fm, _ = parse_skill_md(text)
    assert fm["description"] == "line one\nline two"


def test_parse_skill_md_reads_nested_list_and_map_blocks():
    text = (
        "---\n"
        "name: packer\n"
        "description: 简介\n"
        "tags:\n"
        "  - packmol\n"
        "  - 分子装箱\n"
        "references:\n"
        "  - path: a.md\n"
        "    triggers: [x, y]\n"
        "always: true\n"
        "---\n"
        "body\n"
    )
    fm, _ = parse_skill_md(text)
    assert fm == {
        "name": "packer",
        "description": "简介",
        "tags": ["packmol", "分子装箱"],
        "references": [{"path": "a.md", "triggers": ["x", "y"]}],
        "always": True,
    }


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


def test_default_skill_roots_follow_electromind_home(monkeypatch, tmp_path):
    from electromind.paths import activate_home

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(home))

    activate_home("prod")
    roots = default_skill_roots()
    assert roots == [home / ".electromind" / "skills"]

    activate_home("dev", tmp_path)
    roots = default_skill_roots()
    assert roots == [tmp_path / ".electromind" / "skills"]


def test_registry_from_defaults_accepts_extra_roots(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    extra = tmp_path / "extra"
    extra.mkdir()
    write_skill_dir(extra, "explicit", "显式传入", "body\n")

    registry = SkillRegistry.from_defaults(extra)
    assert "explicit" in registry.names()


def test_registry_from_defaults_missing_dirs_are_ignored(monkeypatch, tmp_path):
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


# ---------------------------------------------------------------------------
# Task 1: discovery tests
# ---------------------------------------------------------------------------


def make_project_skills(project: Path) -> None:
    """Create a minimal project skill set (A+ W5: flat .agents/skills roots).

    Structure::

        <project>/.agents/skills/
        ├── workflow/
        │   └── SKILL.md
        ├── hpc-submit/
        │   └── SKILL.md
        └── knowledge/            # no SKILL.md → never a skill
            └── reference.md
    """
    skills_dir = project / ".agents" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "workflow" / "SKILL.md").parent.mkdir(parents=True)
    (skills_dir / "workflow" / "SKILL.md").write_text(
        "---\nname: workflow\ndescription: 标准工作流\n---\n执行标准工作流。\n",
        encoding="utf-8",
    )
    (skills_dir / "hpc-submit" / "SKILL.md").parent.mkdir(parents=True)
    (skills_dir / "hpc-submit" / "SKILL.md").write_text(
        "---\nname: hpc-submit\ndescription: HPC 提交\n---\n提交 HPC 作业。\n",
        encoding="utf-8",
    )
    kn = skills_dir / "knowledge"
    kn.mkdir(parents=True)
    (kn / "reference.md").write_text(
        "# Reference\nKnowledge base entry.\n", encoding="utf-8"
    )


def make_standard_skill(root: Path, name: str, description: str, body: str) -> Path:
    """Create a standard skill directory (flat layout)."""
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n{body}\n",
        encoding="utf-8",
    )
    return d


# ---- discovery source tests ----


def test_project_structured_skills_dir_no_longer_discovered(tmp_path):
    """DEPRECATED (A+ W5, deadline W8): project skills/ bundles with AGENTS.md
    are no longer a discovery path — only the flat fixed dirs are."""
    project = tmp_path / "project"
    project.mkdir()
    skills_dir = project / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "AGENTS.md").write_text(
        "# Global instructions\nAlways do X.\n", encoding="utf-8"
    )
    wf = skills_dir / "procedures" / "workflow"
    wf.mkdir(parents=True)
    (wf / "SKILL.md").write_text(
        "---\nname: workflow\ndescription: 标准工作流\n---\n执行标准工作流。\n",
        encoding="utf-8",
    )

    sources = discover_skill_sources(str(project))
    structured = [s for s in sources if s.kind == "structured"]
    assert structured == []
    catalog = load_skill_catalog(sources)
    assert catalog.registry.get("workflow") is None


def test_discover_standard_project_skills(tmp_path):
    """A project with .agents/skills/ and .electromind/skills/ is discovered."""
    project = tmp_path / "project"
    project.mkdir()

    agents_dir = project / ".agents" / "skills"
    agents_dir.mkdir(parents=True)
    make_standard_skill(agents_dir, "agent-helper", "agent skill", "body\n")

    em_dir = project / ".electromind" / "skills"
    em_dir.mkdir(parents=True)
    make_standard_skill(em_dir, "em-helper", "em skill", "body\n")

    sources = discover_skill_sources(str(project))
    standard = [s for s in sources if s.kind == "standard"]
    # project sources: .agents/skills, .electromind/skills
    agent_src = [s for s in standard if ".agents" in str(s.root)]
    em_src = [s for s in standard if ".electromind" in str(s.root)]
    assert len(agent_src) == 1
    assert len(em_src) == 1


def test_project_skill_wins_duplicate_user_skill_with_diagnostic(tmp_path):
    """When a project skill and a user skill share a name, the project one wins
    and a diagnostic is emitted."""
    project = tmp_path / "project"
    project.mkdir()
    # Place the project skill in .agents/skills (standard project discovery path)
    project_skills = project / ".agents" / "skills"
    make_standard_skill(
        project_skills, "shared-skill", "project version", "project body\n"
    )

    user_home = tmp_path / "home"
    user_home.mkdir()
    user_skills = user_home / ".electromind" / "skills"
    user_skills.mkdir(parents=True)
    make_standard_skill(user_skills, "shared-skill", "user version", "user body\n")

    sources = discover_skill_sources(str(project), user_home=user_home)
    catalog = load_skill_catalog(sources)

    skill = catalog.registry.get("shared-skill")
    assert skill is not None
    assert skill.description == "project version"
    dupe_diags = [d for d in catalog.diagnostics if d.code == "duplicate_skill_name"]
    assert len(dupe_diags) >= 1


def test_same_scope_duplicate_first_wins(tmp_path):
    """Characterization: 同一 scope（project）内两个来源同名，高优先级来源胜出。

    ``.agents/skills``（priority 2）压过 ``.electromind/skills``（priority 3），
    被遮蔽者只产生 ``duplicate_skill_name`` 诊断而不进入 registry。
    这是 SKILL-3 改为多候选 Catalog 前必须锁定的 first-wins 行为。
    """
    project = tmp_path / "project"
    project.mkdir()
    write_skill_dir(
        project / ".agents" / "skills", "dup-skill", "agents version", "agents body\n"
    )
    write_skill_dir(
        project / ".electromind" / "skills", "dup-skill", "em version", "em body\n"
    )

    sources = discover_skill_sources(str(project))
    catalog = load_skill_catalog(sources)

    skill = catalog.registry.get("dup-skill")
    assert skill is not None
    assert skill.description == "agents version"
    dupe_diags = [d for d in catalog.diagnostics if d.code == "duplicate_skill_name"]
    assert len(dupe_diags) >= 1
    assert "dup-skill" in dupe_diags[0].message


def test_knowledge_is_not_registered_as_skill(tmp_path):
    """`knowledge/` entries (no SKILL.md) are NOT registered as Skills."""
    project = tmp_path / "project"
    project.mkdir()
    make_project_skills(project)

    sources = discover_skill_sources(str(project))
    catalog = load_skill_catalog(sources)

    names = catalog.registry.names()
    assert "workflow" in names
    assert "hpc-submit" in names
    # knowledge/ should never be a skill name
    assert "reference" not in names
    assert "knowledge" not in names


def test_project_skill_symlink_escape_is_rejected(tmp_path):
    """Skill candidates that resolve outside their source root are rejected."""
    project = tmp_path / "project"
    project.mkdir()
    skills_dir = project / ".agents" / "skills"
    skills_dir.mkdir(parents=True)

    outside = tmp_path / "outside"
    outside.mkdir()
    make_standard_skill(outside, "escape-artist", "tries to escape", "body\n")

    # Create a symlink that escapes
    symlink = skills_dir / "escape-artist"
    symlink.symlink_to(outside / "escape-artist")

    sources = discover_skill_sources(str(project))
    catalog = load_skill_catalog(sources)

    # The escaped skill should not be registered
    assert catalog.registry.get("escape-artist") is None
    escape_diags = [
        d for d in catalog.diagnostics if d.code == "skill_resolves_outside_root"
    ]
    assert len(escape_diags) >= 1


def test_catalog_fingerprint_changes_when_skill_md_changes(tmp_path):
    """The fingerprint must change when a SKILL.md body changes (A+ W5:
    there is no AGENTS.md to fingerprint anymore)."""
    project = tmp_path / "project"
    project.mkdir()
    make_project_skills(project)

    sources = discover_skill_sources(str(project))
    catalog1 = load_skill_catalog(sources)
    fp1 = catalog1.fingerprint

    # Change a SKILL.md
    (project / ".agents" / "skills" / "hpc-submit" / "SKILL.md").write_text(
        "---\nname: hpc-submit\ndescription: HPC 提交 v2\n---\n修改后的指令。\n",
        encoding="utf-8",
    )
    catalog2 = load_skill_catalog(sources)
    fp2 = catalog2.fingerprint

    assert fp1 != fp2


def test_discover_sources_includes_user_home_by_default(tmp_path, monkeypatch):
    """When not given a project, user home sources are still discovered."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    user_skills = home / ".electromind" / "skills"
    user_skills.mkdir(parents=True)
    make_standard_skill(user_skills, "user-skill", "a user skill", "body\n")

    sources = discover_skill_sources(None, user_home=home)
    user_srcs = [s for s in sources if s.scope == "user"]
    assert len(user_srcs) >= 1


def test_source_ordering_is_deterministic(tmp_path):
    """The source list must be ordered: project-agents, project-em,
    configured, user-em, user-agents (A+ W5: no structured source)."""
    project = tmp_path / "project"
    project.mkdir()

    # Create .agents/skills and .electromind/skills in project
    (project / ".agents" / "skills").mkdir(parents=True, exist_ok=True)
    (project / ".electromind" / "skills").mkdir(parents=True, exist_ok=True)

    # Create configured root
    configured = tmp_path / "configured-skills"
    configured.mkdir(parents=True, exist_ok=True)

    home = tmp_path / "home"
    home.mkdir()
    (home / ".electromind" / "skills").mkdir(parents=True, exist_ok=True)
    (home / ".agents" / "skills").mkdir(parents=True, exist_ok=True)

    sources = discover_skill_sources(
        str(project),
        configured_roots=(str(configured),),
        user_home=home,
    )

    order = [f"{s.scope}-{s.kind}" for s in sources]
    assert order == [
        "project-standard",
        "project-standard",
        "configured-standard",
        "user-standard",
        "user-standard",
    ]


# ---------------------------------------------------------------------------
# Task 3: progressive disclosure and activation metadata
# ---------------------------------------------------------------------------


def test_global_agents_instructions_removed(tmp_path):
    """DEPRECATED (A+ W5, deadline W8): AGENTS.md global instructions no
    longer exist — skills are self-contained and the prompt has no global
    instruction block."""
    project = tmp_path / "project"
    project.mkdir()
    make_project_skills(project)

    sources = discover_skill_sources(str(project))
    catalog = load_skill_catalog(sources)

    prompt = build_skills_system_prompt(catalog)
    assert "<!-- electromind:skills:start -->" in prompt
    assert "<!-- electromind:skills:end -->" in prompt
    # No global instructions anywhere
    assert "Always do X" not in prompt


def test_initial_prompt_excludes_skill_body(tmp_path):
    """The initial system prompt lists skill names/descriptions but NOT SKILL.md body."""
    project = tmp_path / "project"
    project.mkdir()
    agents_skills = project / ".agents" / "skills"
    agents_skills.mkdir(parents=True)
    make_standard_skill(
        agents_skills,
        "secret-keeper",
        "keeps secrets",
        "SENSITIVE BODY\nDo not show.\n",
    )

    sources = discover_skill_sources(str(project))
    catalog = load_skill_catalog(sources)

    prompt = build_skills_system_prompt(catalog)
    assert "secret-keeper" in prompt
    assert "keeps secrets" in prompt
    # Body must NOT be in the initial prompt
    assert "SENSITIVE BODY" not in prompt
    assert "Do not show" not in prompt


@pytest.mark.asyncio
async def test_use_skill_returns_skill_root_only(tmp_path):
    """A+ CLEAN-007: use_skill payload 只有 skill_root，无 collection 级 skills_root。"""
    project = tmp_path / "project"
    project.mkdir()
    make_project_skills(project)

    sources = discover_skill_sources(str(project))
    catalog = load_skill_catalog(sources)

    mounts = {
        "hpc-submit": SkillMount(
            source_root="project-agents",
            skill_root="/home/agent/.skills/project-agents/hpc-submit",
        ),
    }
    tool = make_use_skill_tool(catalog, mounts)
    result = await tool.acall({"name": "hpc-submit"})
    payload = json.loads(result.content)
    assert payload["ok"] is True
    assert payload["name"] == "hpc-submit"
    assert payload["skill_root"] == "/home/agent/.skills/project-agents/hpc-submit"
    assert "skills_root" not in payload


@pytest.mark.asyncio
async def test_use_skill_returns_resources_and_sha256(tmp_path):
    """use_skill payload includes resources list and sha256."""
    project = tmp_path / "project"
    project.mkdir()
    agents_skills = project / ".agents" / "skills"
    agents_skills.mkdir(parents=True)
    d = agents_skills / "rich-skill"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\nname: rich-skill\ndescription: Has resources\n---\nInstructions here.\n",
        encoding="utf-8",
    )
    (d / "script.sh").write_text("#!/bin/sh\necho run\n")
    (d / "data.json").write_text('{"key": "val"}')

    sources = discover_skill_sources(str(project))
    catalog = load_skill_catalog(sources)

    tool = make_use_skill_tool(catalog)
    result = await tool.acall({"name": "rich-skill"})
    payload = json.loads(result.content)
    assert payload["ok"] is True
    assert "resources" in payload
    assert "script.sh" in payload["resources"]
    assert "data.json" in payload["resources"]
    assert "sha256" in payload
    assert len(payload["sha256"]) == 64


@pytest.mark.asyncio
async def test_use_skill_notifies_activation_observer(tmp_path):
    """on_activate callback is called when use_skill succeeds."""
    project = tmp_path / "project"
    project.mkdir()
    agents_skills = project / ".agents" / "skills"
    agents_skills.mkdir(parents=True)
    make_standard_skill(agents_skills, "event-skill", "triggers event", "Event body.\n")

    sources = discover_skill_sources(str(project))
    catalog = load_skill_catalog(sources)

    activated = []

    def on_activate(skill: Skill) -> None:
        activated.append(skill.name)

    tool = make_use_skill_tool(catalog, on_activate=on_activate)
    result = await tool.acall({"name": "event-skill"})
    payload = json.loads(result.content)
    assert payload["ok"] is True
    assert activated == ["event-skill"]


def test_build_skills_system_prompt_with_catalog_empty_returns_markers(tmp_path):
    """An empty catalog produces the markers block with no skills listed."""
    catalog = load_skill_catalog(())
    prompt = build_skills_system_prompt(catalog)
    assert "<!-- electromind:skills:start -->" in prompt
    assert "<!-- electromind:skills:end -->" in prompt
    assert "暂无可用 skill" in prompt
    # No skill names should be listed
    assert "hpc-submit" not in prompt

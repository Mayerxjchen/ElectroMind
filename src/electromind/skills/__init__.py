"""Skill 机制 —— 目录形式的操作手册 + on-demand 加载。"""

from __future__ import annotations

from .discovery import (
    SkillCatalogSnapshot,
    SkillDiagnostic,
    SkillMount,
    SkillSource,
    discover_skill_sources,
    load_skill_catalog,
)
from .skill import (
    PROJECT_LOCAL_SKILLS_DIR,
    USER_SKILLS_DIR,
    Skill,
    SkillDiscoveryError,
    SkillRegistry,
    build_skills_system_prompt,
    collect_resources,
    default_skill_roots,
    load_skill,
    load_skills_from_root,
    make_use_skill_tool,
    parse_skill_md,
)

__all__ = [
    "PROJECT_LOCAL_SKILLS_DIR",
    "USER_SKILLS_DIR",
    "Skill",
    "SkillCatalogSnapshot",
    "SkillDiagnostic",
    "SkillDiscoveryError",
    "SkillMount",
    "SkillRegistry",
    "SkillSource",
    "build_skills_system_prompt",
    "collect_resources",
    "default_skill_roots",
    "discover_skill_sources",
    "load_skill",
    "load_skill_catalog",
    "load_skills_from_root",
    "make_use_skill_tool",
    "parse_skill_md",
]

"""Skill 机制 —— 目录形式的操作手册 + on-demand 加载。"""

from __future__ import annotations

from .skill import (
    PROJECT_LOCAL_SKILLS_DIR,
    SKILLS_ENV_VAR,
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
    "SKILLS_ENV_VAR",
    "USER_SKILLS_DIR",
    "Skill",
    "SkillDiscoveryError",
    "SkillRegistry",
    "build_skills_system_prompt",
    "collect_resources",
    "default_skill_roots",
    "load_skill",
    "load_skills_from_root",
    "make_use_skill_tool",
    "parse_skill_md",
]

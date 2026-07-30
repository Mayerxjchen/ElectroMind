"""Skill 机制 —— Anthropic 风格的 SKILL.md 目录 + on-demand 加载。

设计要点：
- 每个 skill 是一个目录，根有 `SKILL.md`；frontmatter 声明 name + description，正文是给模型看的指令。
- SkillRegistry 从一个或多个根目录扫描出 skills（每个 skill 目录 = 直接子目录含 SKILL.md）。
- 只把 `name / description` 汇总进 system prompt；模型显式调 `use_skill(name)` 才把完整指令 + 资源清单塞进上下文。
  → 参考 https://www.anthropic.com/news/agent-skills
- Skill 不直接绑定新的 tool；如果一个 skill 需要跑脚本，说明书里让 agent 用 run_command 执行 skill 目录下的脚本即可。

路径来源：
- `from_dirs(*roots)` 完全显式，上层想在哪就在哪；这是给做上层配置的用户最直接的入口。
- `from_defaults(*extra_roots)` 只加载当前 electromind home 下的 `skills/`
  （`./.electromind` 或 `~/.electromind`，与配置/thread 同一根）；`extra_roots` 拼在后面。
- `default_skill_roots()` 单独暴露给需要检查/组合默认路径的上层。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..core.tool import FunctionTool
from ..paths import default_electromind_home

# 兼容旧引用；实际加载走 default_electromind_home()/skills。
PROJECT_LOCAL_SKILLS_DIR = ".electromind/skills"
USER_SKILLS_DIR = "~/.electromind/skills"


@dataclass(frozen=True, slots=True)
class Skill:
    name: str
    description: str
    instructions: str
    root: Path
    resources: tuple[str, ...] = field(default_factory=tuple)
    source_id: str = ""
    skill_root: Path | None = None
    bundle_root: Path | None = None
    sha256: str = ""

    def __post_init__(self) -> None:
        # Ensure root is always set, using skill_root as fallback for compat.
        if self.skill_root is None:
            object.__setattr__(self, "skill_root", self.root)
        if not self.sha256:
            h = __import__("hashlib").sha256()
            h.update(self.instructions.encode("utf-8"))
            h.update(self.description.encode("utf-8"))
            object.__setattr__(self, "sha256", h.hexdigest())


class SkillDiscoveryError(Exception):
    def __init__(self, path: str, reason: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.path = path
        self.reason = reason


class SkillRegistry:
    """内存中的 skill 索引 —— 名字 → Skill。"""

    def __init__(self, skills: list[Skill] | None = None) -> None:
        self.skills: dict[str, Skill] = {}
        for skill in skills or []:
            self.register(skill)

    def register(self, skill: Skill) -> None:
        if skill.name in self.skills:
            raise ValueError(f"duplicate skill name: {skill.name}")
        self.skills[skill.name] = skill

    def get(self, name: str) -> Skill | None:
        return self.skills.get(name)

    def list(self) -> list[Skill]:
        return sorted(self.skills.values(), key=lambda s: s.name)

    def names(self) -> list[str]:
        return sorted(self.skills.keys())

    @classmethod
    def from_dirs(cls, *roots: str | Path) -> SkillRegistry:
        """从一组明确的根目录构建；不读默认路径。"""
        registry = cls()
        for root in roots:
            for skill in load_skills_from_root(root):
                registry.register(skill)
        return registry

    @classmethod
    def from_defaults(cls, *extra_roots: str | Path) -> SkillRegistry:
        """默认路径 + `extra_roots` 一起加载。上层什么都不传就用默认路径。"""
        return cls.from_dirs(*default_skill_roots(), *extra_roots)

    def summary(self, mount: dict[str, str] | None = None) -> str:
        """给 system prompt 用的一段列表。

        `mount` 是 `name -> agent 视角路径` 的映射；如果传了，摘要会告诉
        agent 每个 skill 的资源在电脑上的哪个目录，让它清楚 use_skill 之后
        能直接用 run_command 跑那里的脚本。
        """
        if not self.skills:
            return ""
        lines = [
            "你可以按需加载这些 skill：",
        ]
        for skill in self.list():
            location = mount.get(skill.name) if mount else None
            if location:
                lines.append(f"- `{skill.name}` (在 {location}/)：{skill.description}")
            else:
                lines.append(f"- `{skill.name}`：{skill.description}")
        lines.append(
            "调 `use_skill(name)` 会把对应 skill 的完整说明书和资源清单加载进来。"
        )
        if mount:
            lines.append(
                "资源就放在你自己电脑上，可以用 read_file / run_command 直接访问。"
            )
        return "\n".join(lines) + "\n"


def default_skill_roots() -> list[Path]:
    """默认 skill 搜索路径：当前 electromind home 下的 ``skills/``。"""
    return [default_electromind_home() / "skills"]


def load_skills_from_root(root: str | Path) -> list[Skill]:
    root_path = Path(root).expanduser().resolve()
    if not root_path.exists():
        return []
    if not root_path.is_dir():
        raise SkillDiscoveryError(str(root_path), "not a directory")

    skills: list[Skill] = []
    for entry in sorted(root_path.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        skill_md = entry / "SKILL.md"
        if not skill_md.exists():
            continue
        skills.append(load_skill(entry))
    return skills


def load_skill(skill_dir: str | Path) -> Skill:
    skill_root = Path(skill_dir).expanduser().resolve()
    skill_md = skill_root / "SKILL.md"
    if not skill_md.exists():
        raise SkillDiscoveryError(str(skill_root), "missing SKILL.md")

    frontmatter, body = parse_skill_md(skill_md.read_text(encoding="utf-8"))
    name = str(frontmatter.get("name") or "").strip() or skill_root.name
    description = str(frontmatter.get("description") or "").strip()
    if not description:
        raise SkillDiscoveryError(
            str(skill_md), "frontmatter must include `description`"
        )

    return Skill(
        name=name,
        description=description,
        instructions=body.strip(),
        root=skill_root,
        resources=tuple(collect_resources(skill_root)),
    )


def parse_skill_md(text: str) -> tuple[dict[str, Any], str]:
    """解析 SKILL.md 的 frontmatter：`---\\n<yaml>\\n---\\n<body>`。

    frontmatter 是标准 YAML，直接交给 PyYAML 解析——块标量 `>` / `|`、列表、
    嵌套映射、引号转义都按 YAML 规范处理。没有 frontmatter 时返回 ({}, text)。
    """
    stripped = text.lstrip("\ufeff")
    if not stripped.startswith("---"):
        return {}, stripped

    after_open = stripped[3:]
    end = after_open.find("\n---")
    if end == -1:
        return {}, stripped

    fm_block = after_open[:end]
    body = after_open[end + 4 :]
    if body.startswith("\n"):
        body = body[1:]

    loaded = yaml.safe_load(fm_block)
    frontmatter = loaded if isinstance(loaded, dict) else {}
    return frontmatter, body


def collect_resources(skill_root: Path) -> list[str]:
    """列出 skill 目录里 SKILL.md 以外的相对路径（供说明书里引用）。"""
    resources: list[str] = []
    for dirpath, dirnames, filenames in os.walk(skill_root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for filename in sorted(filenames):
            if filename.startswith("."):
                continue
            full = Path(dirpath) / filename
            rel = full.relative_to(skill_root).as_posix()
            if rel == "SKILL.md":
                continue
            resources.append(rel)
    return sorted(resources)


def make_use_skill_tool(
    registry: SkillRegistry,
    mount: dict[str, str] | None = None,
) -> FunctionTool:
    """构造 `use_skill` 工具。

    `mount` 是 `name -> agent 视角路径` 的映射，通常由 `Sandbox.install_skills`
    产出。传了以后，返回的 `root` 就是 agent 电脑上的路径，agent 可以直接对它
    用 read_file / run_command。没传时 `root` 仍然是宿主机的绝对路径（只是给
    agent 读的字符串，不代表它能访问）。
    """

    async def use_skill(name: str) -> str:
        skill = registry.get(name)
        if not skill:
            return json.dumps(
                {
                    "ok": False,
                    "error": f"未知 skill: {name!r}",
                    "available": registry.names(),
                },
                ensure_ascii=False,
            )
        location = (mount or {}).get(skill.name) or str(skill.root)
        return json.dumps(
            {
                "ok": True,
                "name": skill.name,
                "description": skill.description,
                "instructions": skill.instructions,
                "root": location,
                "resources": list(skill.resources),
            },
            ensure_ascii=False,
        )

    names_hint = ", ".join(f"`{n}`" for n in registry.names()) or "(暂无可用 skill)"
    mount_hint = (
        "返回的 `root` 是你电脑上的路径，可以直接对它 read_file / run_command。"
        if mount
        else "返回的 `root` 只作参考路径。"
    )
    return FunctionTool(
        name="use_skill",
        description=(
            "加载一个 skill 的完整说明书和资源清单。"
            "每个 skill 都是一份现成的操作手册，里面告诉你怎么完成一类任务、可以用哪些脚本。"
            f"当前可用：{names_hint}。"
            "返回 JSON：{name, description, instructions, root, resources[]}。"
            f"{mount_hint}"
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "要加载的 skill 名字。",
                },
            },
            "required": ["name"],
            "additionalProperties": False,
        },
        func=use_skill,
    )


def build_skills_system_prompt(
    registry: SkillRegistry,
    mount: dict[str, str] | None = None,
) -> str:
    """给主 system prompt 追加的一段。空注册表时返回空串。"""
    return registry.summary(mount=mount)

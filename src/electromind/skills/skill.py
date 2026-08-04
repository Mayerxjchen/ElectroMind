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

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import yaml

from ..core.tool import FunctionTool
from ..paths import default_electromind_home

if TYPE_CHECKING:
    from .discovery import SkillCatalogSnapshot, SkillMount

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
    skills_root: Path | None = None
    sha256: str = ""

    def __post_init__(self) -> None:
        # Ensure root is always set, using skill_root as fallback for compat.
        if self.skill_root is None:
            object.__setattr__(self, "skill_root", self.root)
        if not self.sha256:
            h = hashlib.sha256()
            h.update(self.instructions.encode("utf-8"))
            h.update(self.description.encode("utf-8"))
            # Include resource paths so sha256 changes when resources change.
            for res in sorted(self.resources):
                h.update(res.encode("utf-8"))
            object.__setattr__(self, "sha256", h.hexdigest())


class SkillDiscoveryError(Exception):
    def __init__(self, path: str, reason: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.path = path
        self.reason = reason


class SkillRegistry:
    """内存中的 skill 索引 —— 名字 → Skill。

    .. deprecated::
        Phase-2 migration: the runtime now consumes the candidate/catalog
        chain (``SkillCatalogService`` → ``MultiCandidateCatalog`` →
        ``SkillActivationService``).  This class is kept as a compat facade
        (see ``MultiCandidateCatalog.registry``) for legacy callers; new
        code should consume candidates.
    """

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


# Files and directories always excluded from skill resource collection.
_EXCLUDED_NAMES = frozenset(
    {
        ".git",
        ".pytest_cache",
        "__pycache__",
        ".DS_Store",
        "Thumbs.db",
    }
)
_EXCLUDED_SUFFIXES = (".pyc", ".pyo", "~", ".swp", ".swo")


def _is_excluded_path(name: str) -> bool:
    """Return True if the file/directory name should be excluded from resources."""
    if name.startswith("."):
        return True
    if name in _EXCLUDED_NAMES:
        return True
    return any(name.endswith(suffix) for suffix in _EXCLUDED_SUFFIXES)


def collect_resources(skill_root: Path) -> list[str]:
    """列出 skill 目录里 SKILL.md 以外的相对路径（供说明书里引用）。"""
    resources: list[str] = []
    for dirpath, dirnames, filenames in os.walk(skill_root):
        dirnames[:] = [d for d in dirnames if not _is_excluded_path(d)]
        for filename in sorted(filenames):
            if _is_excluded_path(filename):
                continue
            full = Path(dirpath) / filename
            rel = full.relative_to(skill_root).as_posix()
            if rel == "SKILL.md":
                continue
            resources.append(rel)
    return sorted(resources)


_VALID_SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$")


def validate_skill_name(name: str) -> str | None:
    """Return an error message if *name* is invalid, or ``None`` if it is valid.

    Valid names: lowercase letters, digits, and hyphens; must start and end
    with a letter or digit.
    """
    if not name:
        return "skill name must not be empty"
    if not _VALID_SKILL_NAME_RE.match(name):
        return (
            f"invalid skill name {name!r}: "
            "must contain only lowercase letters, digits, and hyphens, "
            "and start/end with a letter or digit"
        )
    return None


def has_symlinks(skill_dir: Path) -> list[Path]:
    """Return a list of symlink paths found anywhere under *skill_dir*.

    An empty list means no symlinks were detected.
    """
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(skill_dir):
        dirnames[:] = [d for d in dirnames if not _is_excluded_path(d)]
        for name in sorted(dirnames + filenames):
            full = Path(dirpath) / name
            if full.is_symlink():
                found.append(full)
    # Also check SKILL.md itself
    skill_md = skill_dir / "SKILL.md"
    if skill_md.is_symlink():
        found.append(skill_md)
    return found


def make_use_skill_tool(
    registry_or_snapshot: SkillRegistry | "SkillCatalogSnapshot",
    mount: dict[str, str] | dict[str, "SkillMount"] | None = None,
    *,
    on_activate: "Callable[[Skill], None] | None" = None,
    generation: int = 0,
    skill_set_digest: str = "",
) -> FunctionTool:
    """构造 `use_skill` 工具。

    Accepts either a ``SkillRegistry`` (legacy) or a ``SkillCatalogSnapshot``.

    When given a snapshot, the ``on_activate`` callback is invoked after a
    successful skill load (only after the payload has been constructed).

    ``mount`` is ``name -> agent 视角路径`` (legacy) or ``name -> SkillMount``.

    ``generation`` and ``skill_set_digest`` are included in the returned
    payload when non-zero/non-empty, so the agent can confirm which version
    of the skill set it is working with.
    """

    # ── resolve the registry ──────────────────────────────────────────
    if isinstance(registry_or_snapshot, SkillRegistry):
        registry = registry_or_snapshot
        snapshot = None
    else:
        snapshot = registry_or_snapshot
        registry = snapshot.registry

    async def use_skill(name: str) -> str:
        from .discovery import SkillMount as _SkillMount

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

        # Build the payload
        sm: "_SkillMount | None" = None
        if mount and skill.name in mount:
            sm = mount[skill.name]

        if isinstance(sm, _SkillMount):
            skill_root = sm.skill_root
            skills_root = sm.skills_root
        else:
            # Legacy: mount is dict[str, str]
            skill_root = (mount or {}).get(skill.name) or str(skill.root)
            skills_root = None

        payload = {
            "ok": True,
            "name": skill.name,
            "description": skill.description,
            "instructions": skill.instructions,
            "skill_root": skill_root,
            "skills_root": skills_root,
            "resources": list(skill.resources),
            "sha256": skill.sha256,
        }
        # Legacy compat: include "root" field for old callers
        payload["root"] = skill_root
        # Include generation and set digest when available
        if generation:
            payload["generation"] = generation
        if skill_set_digest:
            payload["skill_set_digest"] = skill_set_digest

        if on_activate is not None:
            on_activate(skill)

        return json.dumps(payload, ensure_ascii=False)

    names_hint = ", ".join(f"`{n}`" for n in registry.names()) or "(暂无可用 skill)"
    mount_hint = (
        "返回的 `skill_root` 是你电脑上的路径，可以直接对它 read_file / run_command。"
        if mount
        else "返回的 `skill_root` 只作参考路径。"
    )
    return FunctionTool(
        name="use_skill",
        description=(
            "加载一个 skill 的完整说明书和资源清单。"
            "每个 skill 都是一份现成的操作手册，里面告诉你怎么完成一类任务、可以用哪些脚本。"
            f"当前可用：{names_hint}。"
            "返回 JSON：{ok, name, description, instructions, skill_root, skills_root, resources[], sha256}。"
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
    registry_or_snapshot: SkillRegistry | "SkillCatalogSnapshot",
    mount: dict[str, str] | dict[str, "SkillMount"] | None = None,
) -> str:
    """Build the system-prompt block for Skills.

    When given a ``SkillCatalogSnapshot``:
    - Global instructions (AGENTS.md from structured skill roots) appear first.
    - Only skill name, description, source, and mounted root are rendered;
      the SKILL.md instruction body is NOT included.
    - Output is wrapped in ``<!-- electromind:skills:start -->`` /
      ``<!-- electromind:skills:end -->`` markers.

    When given a ``SkillRegistry`` (legacy), the old ``registry.summary()``
    output is returned unchanged.
    """
    from .discovery import SkillCatalogSnapshot  # noqa: F811

    if isinstance(registry_or_snapshot, SkillCatalogSnapshot):
        return _build_snapshot_prompt(registry_or_snapshot, mount)
    return registry_or_snapshot.summary(mount=mount)


def _build_snapshot_prompt(
    snapshot: "SkillCatalogSnapshot",
    mount: dict[str, str] | dict[str, "SkillMount"] | None = None,
) -> str:
    """Render the Skill section from a catalog snapshot."""
    from .discovery import SkillMount

    lines: list[str] = []

    # Global instructions first
    for gi in snapshot.global_instructions:
        gi_clean = gi.strip()
        if gi_clean:
            lines.append(gi_clean)

    lines.append("<!-- electromind:skills:start -->")

    if snapshot.registry.skills:
        lines.append("你可以按需加载这些 skill：")
        for skill in snapshot.registry.list():
            sm = mount.get(skill.name) if mount else None
            if isinstance(sm, SkillMount):
                location = sm.skill_root
                skills_root = sm.skills_root
            elif isinstance(sm, str):
                location = sm
                skills_root = None
            else:
                location = ""
                skills_root = None

            extra = ""
            if skills_root:
                extra = f"，root: {skills_root}"
            # Show a short source label without full filesystem paths
            source_label = _short_source_label(skill.source_id)
            lines.append(
                f"- `{skill.name}`（{source_label}）：{skill.description}"
                + (f" @ {location}{extra}" if location else "")
            )
        lines.append(
            "调 `use_skill(name)` 会把对应 skill 的完整说明书和资源清单加载进来。"
        )
        if mount:
            lines.append(
                "资源就放在你自己电脑上，可以用 read_file / run_command 直接访问。"
            )
    else:
        lines.append("(暂无可用 skill)")

    lines.append("<!-- electromind:skills:end -->")
    return "\n".join(lines) + "\n"


def _short_source_label(source_id: str) -> str:
    """Return a short human-readable label from a source id.

    ``source_id`` format is ``{scope}-{kind}-{root_path}``.
    We strip the filesystem path and return just ``scope/kind``.
    """
    parts = source_id.split("-", 2)
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return source_id

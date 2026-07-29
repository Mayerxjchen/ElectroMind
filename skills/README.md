# ElectroMind Skills

This directory follows the AICC (AI-Computational-Chemist) convention.

## Ownership

This directory is the editable source of ElectroMind's local skills.
ElectroMind owns and versions this copy; runtime discovery does not read an
external skill checkout.

## Directory layout

```
skills/
├── AGENTS.md       # Required: global routing rules, safety boundaries
├── STRUCTURE.md    # Recommended: repository structure convention
├── README.md       # This file
├── procedures/     # Multi-step workflow skills
│   └── <name>/
│       ├── SKILL.md
│       ├── references/
│       ├── examples/
│       └── scripts/
├── tools/          # Single-purpose operation skills
│   └── <name>/
│       ├── SKILL.md
│       ├── references/
│       ├── examples/
│       └── scripts/
└── knowledge/      # Shared reference material (never registered as skills)
    └── <topic>.md
```

## Discovery

Only direct children of `procedures/` and `tools/` containing `SKILL.md`
are registered as routable skills. `knowledge/` is shared reference material
and is never registered as a skill. Hidden directories are ignored.

## Session initialization

`AGENTS.md` is loaded at session start and injected into the system prompt
before skill metadata. Root-relative cross-references to `knowledge/`, `tools/`, and `procedures/`
remain unchanged in `SKILL.md`. `use_skill` returns the mounted `skills_root`;
the agent resolves those native relative paths beneath that root.

## Skill contract

- `SKILL.md` frontmatter requires `name` and `description`.
- Skill names are globally unique across procedures, tools, and roots.
- ElectroMind discovers skills from configured `[skills].roots`.
- Use `use_skill("skill-name")` to load full instructions, resources, and
  the mounted `skills_root`.
- `electromind doctor` validates the AICC directory convention.

## Adding a skill

1. Create a directory under `procedures/` or `tools/`.
2. Add `SKILL.md` with YAML frontmatter (`name` and `description`).
3. Add `references/`, `examples/`, and `scripts/` as needed.
4. Run `electromind doctor` to validate.

## Examples

Domain tools such as ai2-kit, Packmol, and DeepMD workflows are user Skills.
Clone or install them under your project's `skills/` directory or under
`~/.config/electromind/skills/`.

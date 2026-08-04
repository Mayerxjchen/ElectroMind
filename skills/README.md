# ElectroMind Skills

This directory follows the AICC (AI-Computational-Chemist) convention, under
the A+ / self-contained skills model: every skill is an independent, fully
self-contained standard skill in the Git worktree, in the wheel, in the
installed environment, and at runtime.

## Ownership

This directory is the editable source of ElectroMind's local skills.
ElectroMind owns and versions this copy; runtime discovery does not read an
external skill checkout.

## Directory layout

```
skills/
├── README.md        # This file
├── procedures/      # Multi-step workflow skills
│   └── <skill>/
│       ├── SKILL.md
│       ├── references/
│       │   └── knowledge/   # committed runtime copies (sync-managed)
│       ├── scripts/
│       └── examples/
├── tools/           # Single-purpose operation skills
│   └── <skill>/
│       ├── SKILL.md
│       ├── references/
│       │   └── knowledge/   # committed runtime copies (sync-managed)
│       ├── scripts/
│       └── examples/
└── knowledge/       # canonical authoring source (NOT a runtime dependency)
    ├── sync-map.toml
    └── sync-manifest.json
```

## Knowledge: authoring source vs runtime copies

- `skills/knowledge/` is the **canonical authoring source** only. No skill may
  depend on it at runtime — not even when running from the source tree.
- Each skill that uses a knowledge document carries its own **committed
  byte-identical copy** under `<skill>/references/knowledge/`, declared in
  `skills/knowledge/sync-map.toml` (explicit mapping, no semantic slicing).
- Reconcile copies with `uv run scripts/sync-skill-references.py`; verify
  (read-only) with `uv run scripts/sync-skill-references.py --check`.

## Discovery

ElectroMind knows exactly two plain flat roots: `skills/procedures/` and
`skills/tools/`. Only direct children containing `SKILL.md` are registered as
routable skills. The directory name must equal the frontmatter `name` (hard
error otherwise). There is no collection manifest, no structured root marker,
and no shared mounting.

## Self-containment contract

- `SKILL.md` frontmatter requires `name` (== directory name) and `description`.
- All local Markdown links resolve inside the skill (reference closure);
  knowledge links point at the skill's own `references/knowledge/`.
- Cross-skill collaboration is expressed by **name only**: “Activate the
  `X` skill …”. ElectroMind's activation tool maps that wording to
  `use_skill`/`activate_skill`; other hosts map it to their own mechanism.
  A missing skill reports `required capability unavailable: <name>`.
- `scripts/check-skill-isolation.py` enforces the contract
  (run in CI via `scripts/ci-check.sh`).

## Adding a skill

1. Create a directory under `procedures/` or `tools/` named after the skill.
2. Add `SKILL.md` with YAML frontmatter (`name` matching the directory,
   `description` carrying the capability details).
3. Add `references/`, `examples/`, and `scripts/` as needed.
4. If the skill needs shared science, add a `[[references]]` entry in
   `skills/knowledge/sync-map.toml` and run the sync script.
5. Run `electromind doctor` and `scripts/check-skill-isolation.py` to validate.

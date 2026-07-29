# Skills Directory Structure

```text
skills/
├── AGENTS.md       # global rules, routing policy, safety boundaries
├── STRUCTURE.md    # this file
├── README.md       # authoring guide
├── procedures/     # multi-step workflow skills
├── tools/          # per-code operation skills
└── knowledge/      # shared reference material (never registered as skills)
```

Only direct children of `procedures/` and `tools/` containing `SKILL.md`
are registered as routable skills. `knowledge/` is shared reference material
and is never registered as a skill.

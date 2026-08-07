---
name: packmol
description: >
  Generate and validate initial Packmol configurations from specified molecule
  or ion structures, counts, target density or box dimensions. Use when a user
  needs an auditable packed starting geometry for molecular simulation.
compatibility: Requires Python 3 and a Packmol executable in the execution environment.
license: LGPL-3.0-or-later
metadata:
  author: xjchen
  version: "4.0"
  upstream_repository: https://github.com/m3g/packmol
  requires:
    os: [linux, darwin]
    requires:
      bins: [python3]
---

# Packmol Generate

Generate an auditable initial molecular configuration. Packmol produces initial
packing, not equilibration; ordinary XYZ does not preserve the cell, topology,
charges, force-field parameters, or DFT settings.

## When to use

Use when a packed starting geometry is needed — mixtures, electrolytes, salts,
solvents, ions, or any multi-component box at a target density or box size —
and a Packmol executable is available. The output is `preparation_stage:
"packed"`, not simulation-ready: it still needs cell/topology assignment,
minimization, and equilibration.

## Required inputs

- Component identity/count and one single-molecule or ion XYZ per component
- Formal charges for ionic components
- Target density **or** fixed box dimensions (exactly one)
- Periodic versus non-periodic mode, tolerance, output paths, system name

Do not invent or silently default scientific values; ask for missing facts. If
automation cannot ask, stop with an exact missing-input report.

## Procedure (5 steps)

1. Resolve scientific inputs (composition, charge, density/box).
2. Write `packmol-task.json` — schema in `references/task-manifest.md`.
3. Run preflight + input validation: `preflight.py`, then `validate_manifest.py`;
   continue only when both pass.
4. Generate and execute Packmol: `build_packmol_input.py`, then run Packmol with
   explicit input redirection, timeout, and exit-code preservation. Keep failed
   attempts; troubleshoot before any controlled retry.
5. Validate, QC, and deliver: `validate_packmol_result.py`, then `qc_structure.py`.

Full execution sequence, box formula, and result-record names:
`references/running.md`. Completion criteria and QC details:
`references/validation.md`.

## Key guardrails

- Packing is not equilibration; the packed box is not production-ready.
- Composition, charge, and density/box are scientific inputs — never invented or
  silently defaulted; defaults must be explicitly accepted and recorded.
- Periodic work follows the PBC rules in `references/packmol-pbc.md` and QC
  pattern in `references/pbc-qc-pattern.md`.
- Result records are named JSON — never replace missing records with prose.

## Where to find what

| Situation | Go to |
|---|---|
| task manifest JSON schema, field rules, box formula | `references/task-manifest.md` |
| full step-by-step execution and result-record names | `references/running.md` |
| result validation, QC gates, completion criteria | `references/validation.md` |
| periodic packing rules | `references/packmol-pbc.md` |
| QC pattern for periodic boxes | `references/pbc-qc-pattern.md` |
| mixtures, electrolytes, salts, solvents, ions composition | `references/packmol-mixture.md` |
| Packmol version, success markers, constraint violations | `references/packmol-official.md` |
| failed, timed-out, hanging, empty, overlapping results | `references/packmol-troubleshooting.md` |

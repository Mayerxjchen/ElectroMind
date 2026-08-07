# Upstream ai2-kit TESLA vs This Procedure

> Load this when: comparing with the official ai2-kit TESLA examples, or
> deciding how much of the upstream workflow to adopt.

## What upstream provides

- The `chenggroup/ai2-kit` repository ships TESLA active-learning workflow
  examples under `example/use-case/`:
  - `tesla` — the canonical Train-Explore-Screen-Label workflow
  - `tesla-for-ec-mlp` — TESLA for electrolyte MLP training
  - `tesla-pimd` — TESLA variant using PIMD
- Each example follows the same skeleton: `00-config/` (DeepMD, LAMMPS, CP2K,
  Slurm templates), `01-workflow/` (strategy scripts such as
  `iter-basic-dp-lammps-cp2k.sh`), a workdir, and a top-level `run.sh` that
  walks iterations.
- The repository also bundles a `build-tesla` skill that generates TESLA
  workflow code from the examples.

## The critical difference

Upstream `build-tesla` explicitly does **not** require executing the generated
code. This procedure is the real-execution counterpart:

```text
upstream: generate workflow code            this skill: run the real loop
```

Real execution means this skill owns, per iteration:

- **Preflight** — validate the project skeleton and the current iteration
  before spending HPC hours (`scripts/check_tesla_project.py`,
  `scripts/check_iteration.py`).
- **Monitoring** — job states and logs through `hpc-submit` / `rsess`, not a
  paper plan.
- **Parsing** — lcurve, model deviation, DFT outputs, dataset updates parsed
  deterministically (`scripts/summarize_iteration.py` and the tool skills).
- **Scientific validation** — every stage gets a VALIDATED verdict separate
  from mere completion; `*.done` is not enough.
- **Recovery** — resume the earliest incomplete stage after failures, with
  duplicate-label protection.
- **Stopping** — the loop ends on exploration convergence plus physics
  validation, not on example defaults.

## How to use upstream artifacts here

1. Adopt the directory skeleton and strategy scripts as a starting point.
2. Read the target example's `run.sh` to learn its actual workdir name and
   iteration numbering (upstream currently uses `10-workdir/`; this
   repository's convention is `20-workdir/`).
3. Replace template parameters with project decisions: temperature, replicas,
   steps, thresholds, model count.
4. Treat the example's thresholds and settings as starting points only; every
   value must be justified for the current system.
5. Keep the provenance: `references/iteration-manifest.md` records what was
   actually done in each iteration.

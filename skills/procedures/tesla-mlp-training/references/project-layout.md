# Project Layout

> Load this when: creating or inspecting a TESLA project, writing `run.sh`,
> or locating stage artifacts inside an iteration.

## Top level

```text
<project>/
├── 00-config/     templates and shared inputs
├── 01-workflow/   strategy scripts, per-iteration drivers
├── 20-workdir/    per-iteration work and artifacts
└── run.sh         top-level driver
```

- `00-config/` holds the template files the strategy scripts copy per stage:
  DeepMD `input.json` (and descriptor/model seeds), LAMMPS input templates,
  CP2K/VASP input templates, Slurm scripts.
- `01-workflow/` holds executable strategy scripts (e.g.
  `iter-basic-dp-lammps-cp2k.sh`) that turn the config templates into actual
  stage inputs. Copy and edit a strategy script per project rather than
  rewriting it from scratch.
- `20-workdir/` holds iteration directories. Upstream examples may name this
  `10-workdir/`; read the adopted example's `run.sh` to confirm.
- `run.sh` is the top-level driver: it walks iterations, calls the strategy
  scripts, and writes stage done markers. It is project-owned code, not a
  skill artifact — `ai2kit` never generates or edits it (boundary freeze).

## Iteration directory

```text
20-workdir/iter-1/
├── 01_train/            DeepMD training output: graph.000.pb ... graph.NNN.pb, lcurve.out
├── 02_explore/          replica dirs, each with trajectory dump + model_devi.out
├── 03_screen/           selected.xyz (and grading statistics) from the screen stage
├── 04_label/            per-frame DFT outputs (e.g. CP2K run directories)
├── 05_update/           updated dpdata dataset dir (type.raw, set.NNN, ...)
├── 01_train.done        completion markers: <stage>.done
├── 02_explore.done
├── 03_screen.done
├── 04_label.done
├── 05_update.done
├── 01_train.validated   validation records: <stage>.validated (written only
├── ...                  when the stage's VALIDATED conditions hold)
└── iteration-manifest.json
```

Iteration numbering: `iter-<n>` with `n` starting at 1 and increasing by 1 per
iteration. `iter-0` is not an iteration; the initial dataset is built before
the first iteration (see `references/initial-dataset.md`).

## Markers

- `<stage>.done` — written by the orchestrator when the stage's execution
  finished (success or failure is recorded in logs; the marker alone is
  ambiguous, so a failed run must not leave one).
- `<stage>.validated` — written only when the stage passed its VALIDATED
  checks (`references/iteration-validation.md`). Its existence is the only
  proof of validity.
- Done markers are checked by `scripts/check_iteration.py`, which reports
  `completed` and `validated` as separate fields.

## What is not stored here

- HPC submission records and scheduler state live with `hpc-submit` job
  records, not in the iteration tree.
- No separate research DAG: TESLA run state (iterations, workdir, done
  markers, datasets, models, jobs) is the source of truth. Only large
  multi-study campaigns add `research-orchestrator` state on top.

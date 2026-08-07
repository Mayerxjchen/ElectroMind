---
name: tesla-mlp-training
description: >
  Orchestrate end-to-end TESLA machine-learning interatomic-potential
  training on HPC: Train-Explore-Screen-Label iterations with real
  execution, monitoring, parsing, scientific validation, recovery, and
  stopping criteria, using ai2-kit + oh-my-batch + DeepMD + LAMMPS +
  CP2K/VASP. Use for active-learning MLIP workflows; the underlying
  programs are operated by their own tool skills.
---

# TESLA MLP Training Procedure

This is the core **procedure skill** for machine-learning interatomic-potential
work. It decides what to do and when: the Train-Explore-Screen-Label
Active-learning (TESLA) loop on HPC, with real execution, monitoring, parsing,
scientific validation, recovery, and stopping criteria.

It does **not** implement the underlying software. Each stage is executed and
validated by its tool skill: `ai2kit` (data conversion, model-deviation
processing), `deepmd` (training), `lammps` (exploration MD), `cp2k` / `vasp`
(labeling DFT), `hpc-submit` / `rsess` (HPC execution), `packmol` /
`structure-prep` (initial configurations).

This is not a copy of the official `build-tesla` skill from the upstream
`chenggroup/ai2-kit` repository: upstream explicitly does not require executing
the generated code. This ElectroMind skill runs the real loop end to end.

## Lifecycle

```text
Build -> Preflight -> Execute -> Monitor -> Parse -> Validate
  -> Recover -> Next iteration -> Stop/Continue -> Final validation
```

## Directory convention (follows upstream)

```text
<project>/
├── 00-config/     templates: DeepMD input.json, LAMMPS input, CP2K/VASP inputs, Slurm scripts
├── 01-workflow/   strategy scripts (e.g. iter-basic-dp-lammps-cp2k.sh), per-iteration drivers
├── 20-workdir/    per-iteration work: <iter-id>/01_train, 02_explore, 03_screen, 04_label, 05_update
└── run.sh         top-level driver that walks iterations
```

The workdir is named `20-workdir/` in this repository's convention; the
upstream example currently uses `10-workdir/` — when adopting an upstream
example verbatim, read its `run.sh` for the actual name.

TESLA itself is the source of truth for run state: iterations, workdir, done
markers, datasets, models, and jobs. ElectroMind keeps only HPC submission
records, parser validation, and artifact hashes alongside it. Do not maintain
a separate research DAG unless the project grows into a large multi-study
campaign (then consult `research-orchestrator`).

## Stage responsibilities

| Stage | Owner skill | VALIDATED conditions |
|---|---|---|
| INIT | `ai2kit` + `cp2k`/`vasp`/`lammps`/`packmol`/`structure-prep` | frames/types/energies/forces/cell complete; dataset fingerprint consistent |
| TRAIN | `deepmd` | model generated; lcurve sane; no NaN |
| EXPLORE | `lammps` | normal termination; 0 lost atoms; trajectory and model deviation complete |
| SCREEN | `ai2kit` | model deviation parseable; frame mapping consistent; candidates valid |
| LABEL | `cp2k` / `vasp` | DFT normal end; SCF converged; energies/forces complete |
| UPDATE | `ai2kit` (dpdata) | dataset readable; frame count correct; type_map/fingerprint unchanged |
| ITERATION VALIDATION | this skill | all stage validations above passed |
| NEXT / STOP | this skill | exploration uncertainty low + physics validation passed (see `references/stopping.md`) |
| FINAL | this skill + `deepmd` + `lammps` | held-out error + MD stability + target physical observables |

HPC execution and monitoring route to `hpc-submit` / `rsess` at every stage.

**`*.done` means COMPLETED, never VALIDATED.** A done marker proves the stage
ran; validity is a separate scientific verdict recorded per stage (see
`references/iteration-validation.md`).

## Iteration Manifest (provenance per iteration)

Each iteration keeps a minimal machine-readable manifest (`iteration-manifest.json`
in the iteration directory) so provenance survives restarts and handoffs:
`iteration_id`, `parent_dataset_digest`, `training_dataset_digest`, `models[]`,
`exploration_conditions[]`, `candidate_count`, `selected_count`,
`label_success_count`, `label_failure_count`, `updated_dataset_digest`,
`validation_status`. Schema and example: `references/iteration-manifest.md`.
This is TESLA's own provenance record, not a research DAG.

## Where to find what

| Situation | Go to |
|---|---|
| how upstream ai2-kit/TESLA differs from this procedure; example sources | `references/upstream-ai2kit.md` |
| full directory layout, iteration directory contents, done/validated markers | `references/project-layout.md` |
| build the initial dataset (coverage-first, no fixed frame count) | `references/initial-dataset.md` |
| the TRAIN stage via `deepmd`: input.json, lcurve, freeze/compress, QA | `references/train.md` |
| the EXPLORE stage via `lammps`: conditions, replicas, deviation output | `references/explore.md` |
| the SCREEN stage via `ai2kit`: parsing, grading, candidate selection | `references/screen.md` |
| the LABEL stage via `cp2k`/`vasp`: ENERGY_FORCE, per-frame validation, dedupe | `references/label.md` |
| dataset updates, fingerprint invariance, re-splitting | `references/update.md` |
| per-stage VALIDATED checklists, COMPLETED vs VALIDATED | `references/iteration-validation.md` |
| the iteration manifest schema and example | `references/iteration-manifest.md` |
| HPC recovery, job resume, restarting an iteration | `references/recovery.md` |
| when to stop the active-learning loop | `references/stopping.md` |
| oh-my-batch (omb) combo/batch/job usage | `references/oh-my-batch.md` |
| upstream links and related documentation | `references/resources.md` |
| check project/iteration/dataset structure and summarize a run | `scripts/check_tesla_project.py`, `scripts/check_iteration.py`, `scripts/check_dataset_fingerprint.py`, `scripts/summarize_iteration.py` |
| the water64 golden-path walkthrough and placeholders | `examples/water64/README.md` |

## Hard guardrails

- **No global fixed frame count** defines a production-ready initial dataset.
  Sufficiency is assessed by configuration-space coverage, held-out
  accuracy, model deviation/uncertainty, active-learning convergence, MD
  stability, and target physical observables. 50/500/10000 frames are project
  parameters, not rules.
- **One dataset = one method fingerprint.** All labels in a training dataset
  share functional, basis/cutoff, k-point policy, U values, spin policy,
  convergence thresholds, and pseudopotential family. A method change starts a
  new dataset (see `references/update.md`).
- **Model quality is judged on held-out data only**, never on training frames:
  held-out error, learning curve, parity, coverage, physics.
- **Production MD must be validated inside the training distribution**:
  composition, phase, volume/strain, temperature, relevant reactive/diffusive
  events. A potential trained on cold, unstrained water does not certify hot
  or compressed water.
- **Iteration stopping condition** = low exploration uncertainty (consecutive
  iterations yield few/high-quality candidates) **and** physics validation
  passed. No fixed iteration count is a stopping rule.
- **HPC submissions never bypass tool approval**: every batch routes through
  `hpc-submit` (and `rsess` for persistent remote sessions), with the target
  cluster conventions read first.
- **Never resubmit blindly**: on failure, read scheduler state, logs, and
  stage markers, identify the earliest incomplete stage, and resume from
  there (`references/recovery.md`).
- **`*.done` is not validity**: every stage keeps a separate VALIDATED
  verdict; an unvalidated iteration never feeds the next one silently.

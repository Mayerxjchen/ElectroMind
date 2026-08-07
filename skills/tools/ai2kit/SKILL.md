---
name: ai2kit
description: >
  Operate and validate ai2-kit utilities used in machine-learning
  interatomic-potential workflows, including ASE/dpdata data conversion,
  model-deviation processing, ai2-kit environment/version checks, and
  TESLA-related data/tool handoffs. Use tesla-mlp-training for the
  multi-stage Train-Explore-Screen-Label workflow itself.
---

# ai2-kit (AI2Kit) Toolbox

This skill operates and validates the `ai2-kit` command-line and Python toolkit
(upstream `chenggroup/ai2-kit`) used inside machine-learning interatomic-potential
workflows: ASE/dpdata data conversion, model-deviation processing, environment
and version checks, and data/tool handoffs to and from TESLA iterations.

It is a **tool skill**: it owns how `ai2-kit` runs, what it checks, and how to
validate its inputs and outputs. The full multi-stage Train-Explore-Screen-Label
(TESLA) workflow — iteration management, run.sh generation, job retry, and
stopping criteria — belongs to `tesla-mlp-training`, not here.

## Where to find what

| Situation | Go to |
|---|---|
| detect the ai2-kit environment, typical one-shot usage, TESLA data handoffs | `references/running.md` |
| dpdata System/DataSet conversion, type_map contract, DeepMD data handoff | `references/dpdata.md` |
| ASE Atoms reading/writing, structure manipulation, ASE-dpdata interchange | `references/ase.md` |
| parse and filter `model_devi.out`: grading, frame mapping, statistics | `references/model-deviation.md` |
| version and compatibility checks, CLI drift handling | `references/versions.md` |
| command fails, parse errors, missing dependencies, frame mismatches | `references/errors.md` |
| upstream repository, manuals, examples, official build skill | `references/resources.md` |
| run the deterministic environment/data/model-deviation checks | `scripts/check_ai2kit.py`, `scripts/check_dpdata_system.py`, `scripts/check_model_devi.py` |
| minimal example command sequences to copy and adapt | `examples/README.md` |

## What this skill owns

- Detect the `ai2-kit` executable / Python package, report the version, verify
  required subcommands, and check that the optional `dpdata` / ASE /
  model-deviation features are available (`scripts/check_ai2kit.py`).
- Operate the data tools: dpdata dataset reading, slicing, sampling, and
  conversion between dpdata, ASE and other structure formats.
- Operate model-deviation processing: read a trajectory plus `model_devi.out`,
  grade frames, dump grading statistics, and write selected frames.
- Check upstream examples (e.g. the TESLA use cases) and detect CLI drift
  between the installed `ai2-kit` and this documentation.

## What this skill does not own

| Task | Owner |
|---|---|
| `dp train` / `dp freeze` / `dp compress` / `dp test`, lcurve/QA | `deepmd` |
| LAMMPS input files and MD execution | `lammps` |
| CP2K ENERGY_FORCE labeling runs | `cp2k` |
| VASP labeling runs | `vasp` |
| Slurm/PBS submission, job monitoring, resume | `hpc-submit` |
| initial-structure packing and preparation | `packmol`, `structure-prep` |
| the full TESLA iteration loop, run.sh generation, stopping criteria | `tesla-mlp-training` |

## Hard guardrails

- Do not copy large amounts of upstream source code or a full CLI reference
  into this skill. `ai2-kit` is under active development and its API changes;
  treat every concrete CLI surface as provisional.
- CLI parameter truth order: `ai2-kit --help` -> installed package source ->
  upstream documentation. Never assume a subcommand or flag from memory.
- The scripts in `scripts/` perform deterministic validation only. They never
  reimplement dpdata conversion or model-deviation computation.
- **Boundary freeze**: run.sh generation, iteration management, job retry, and
  stopping criteria never move into this skill, regardless of convenience.
  They belong to `tesla-mlp-training`.
- No global model-deviation thresholds live here. Grading thresholds (lo/hi),
  candidate counts, and exploration strategy are project parameters owned by
  `tesla-mlp-training`.
- Every reported number needs provenance: file path, parsing rule, and (where
  relevant) the observed `ai2-kit` version.

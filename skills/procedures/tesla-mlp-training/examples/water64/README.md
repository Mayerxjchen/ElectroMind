# water64 — TESLA Golden Path (documented, no data committed)

This example documents the golden-path chain for a first usable water
machine-learning potential in a 64-molecule water box. It is a **walkthrough
and layout placeholder only**: no real data, no real jobs. The `fixtures/`
and `expected/` directories describe what tiny synthetic fixtures would look
like (a future PR-7-style acceptance run), and `00-config/` / `01-workflow/`
hold template descriptions, not committed templates.

## The chain

```text
packmol: 64 H2O box
  -> LAMMPS classical MD: initial configurations at target T
  -> CP2K ENERGY_FORCE: labels for distinct sampled frames
  -> ai2-kit / dpdata: build the INIT dataset (method fingerprint recorded)
  -> DeepMD: train a committee (e.g. 4 models) on the dataset
  -> LAMMPS exploration MD with the committee at target conditions
  -> ai2-kit model_devi: grade frames, select candidates
  -> CP2K: label new candidates (per-frame VALIDATED contract)
  -> update: merge labels into the dataset (fingerprint unchanged)
  -> iterate until exploration uncertainty is low + physics validates
  -> dp test on held-out frames
  -> MD stability run at production conditions
  -> RDF (and other observables) vs reference
  -> first usable water potential
```

Each step routes to its owning skill: `packmol` / `structure-prep`,
`lammps`, `cp2k`, `ai2kit`, `deepmd`, and `hpc-submit` / `rsess` for HPC
execution. `tesla-mlp-training` orchestrates the loop.

## Directory placeholders

| Directory | Purpose |
|---|---|
| `00-config/` | template descriptions for DeepMD input.json, LAMMPS input, CP2K input, Slurm scripts (see its README) |
| `01-workflow/` | strategy-script descriptions (e.g. an `iter-basic-dp-lammps-cp2k`-style driver; see its README) |
| `fixtures/` | tiny synthetic fixtures (fake init dataset, lcurve.out, model_devi.out, small CP2K outputs) for logic acceptance — no real data |
| `expected/` | expected outputs/verdicts for the fixture run (see its README) |

## Rules

- **No real data is committed here**: no AIMD trajectories, no real DFT
  outputs, no trained models, no project paths.
- Numbers in the walkthrough (temperatures, thresholds, committee size,
  frame counts) are illustrative project parameters, not defaults — every
  value is a project decision (`references/initial-dataset.md`,
  `references/screen.md`).
- The real water64 run is scientific acceptance, not a skill test: it
  follows the full lifecycle with real execution and FINAL validation.

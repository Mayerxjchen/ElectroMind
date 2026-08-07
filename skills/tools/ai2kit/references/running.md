# Running ai2-kit

> Load this when: you need to detect the ai2-kit environment, run a typical
> one-shot data or model-deviation operation, or hand data to/from TESLA.

## Environment detection

`ai2-kit` is distributed as a Python package (upstream supports Python 3.10-3.12).

```bash
which ai2-kit            # CLI entry point present?
ai2-kit --version        # fallback: ai2-kit version
ai2-kit --help           # top-level subcommand groups
ai2-kit tool --help      # tool group surface (dpdata / ase / model_devi / ...)
pip show ai2-kit         # installed version and location
```

For a single deterministic verdict, run `scripts/check_ai2kit.py`; it reports
binary/import/version/required-subcommand/feature availability as JSON and
never fails on a missing installation.

## Stable concepts

- **Chainable pipelines.** The tool group composes a read -> transform -> write
  pipeline in one command line; steps are separated by a single `-`. Reading
  alone is useless by design — every read must be chained to a consumer step.
- **read then transform then write.** Typical chains: `read` datasets or
  trajectories, then `slice`/`sample`/`grade`, then `write`/`write_frames`.
- **drift awareness.** Subcommand and flag names change between releases.
  Concrete parameters below are examples, not contracts: confirm each with
  `ai2-kit <subcommand> --help` at use time (see `references/versions.md`).

## Typical one-shot operations

Convert a dpdata system to an ASE object and write frames as XYZ:

```bash
ai2-kit tool dpdata read ./dp-h2o --fmt deepmd/npy \
  - to_ase - write h2o.xyz
```

Drop the first 10 frames, randomly sample 10, and write XYZ:

```bash
ai2-kit tool dpdata read ./dp-h2o --fmt deepmd/npy \
  - slice 10: - sample 10 --method random - to_ase - write h2o.xyz
```

Write each frame as a VASP POSCAR (numbered output pattern):

```bash
ai2-kit tool dpdata read ./dp-h2o --fmt deepmd/npy \
  - to_ase - write_frames "./vasp-{i-04d}/POSCAR" --format vasp
```

Grade exploration frames by force deviation and keep the candidates:

```bash
ai2-kit tool model_devi read "./workdir/lammps/*" \
  --traj_file dump.lammpstrj --md_file model_devi.out \
  - grade --lo 0.1 --hi 0.2 --col max_devi_f \
  - dump_stats stats.tsv \
  - write selected.xyz --level decent
```

The `model_devi` `read` step validates that the trajectory and the deviation
file cover the same number of frames; a mismatch fails the chain.

## TESLA data handoffs

- Data produced here (converted initial datasets, labeled frames, screened
  candidates) feeds `tesla-mlp-training` iterations.
- Thresholds, candidate counts, and what happens next are decisions of
  `tesla-mlp-training`; this skill only executes and validates the tool steps.
- Record the observed `ai2-kit` version next to any handoff artifact so later
  drift is diagnosable (`references/versions.md`).

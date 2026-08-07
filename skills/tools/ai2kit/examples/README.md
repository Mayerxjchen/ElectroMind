# ai2-kit Examples

Place small, privacy-neutral ai2-kit examples here. Do not commit real datasets,
proprietary trajectories, or project-specific paths.

## When to use this skill vs `tesla-mlp-training`

| Situation | Use |
|---|---|
| convert/validate a dpdata dataset, slice/sample frames, ASE round-trips | `ai2kit` |
| parse/grade a `model_devi.out`, write candidate frames | `ai2kit` |
| check whether ai2-kit is installed and which features work | `ai2kit` |
| decide what to explore, thresholds, iteration flow, stopping | `tesla-mlp-training` |
| full Train-Explore-Screen-Label loop on HPC with monitoring/recovery | `tesla-mlp-training` |

## Minimal command sequences

Environment check (JSON verdict; missing ai2-kit reports `missing` and exits 0):

```bash
python ../scripts/check_ai2kit.py --python "$(which python)"
```

dpdata conversion — read a system, drop the first 10 frames, sample 10, write
XYZ (exact flags per `ai2-kit tool dpdata --help`):

```bash
ai2-kit tool dpdata read ./dp-h2o --fmt deepmd/npy \
  - slice 10: - sample 10 --method random - to_ase - write h2o.xyz
```

Validate the result before handoff:

```bash
python ../scripts/check_dpdata_system.py --system ./dp-h2o
```

model_devi parsing — grade exploration frames and write candidates
(exact flags per `ai2-kit tool model_devi --help`):

```bash
ai2-kit tool model_devi read "./workdir/lammps/*" \
  --traj_file dump.lammpstrj --md_file model_devi.out \
  - grade --lo 0.1 --hi 0.2 - write selected.xyz --level decent
```

Validate the deviation file first:

```bash
python ../scripts/check_model_devi.py --md-file ./workdir/lammps/0/model_devi.out
```

The concrete flags above are examples, not contracts — `ai2-kit` releases
change them; confirm with `--help` at use time (`references/versions.md`).

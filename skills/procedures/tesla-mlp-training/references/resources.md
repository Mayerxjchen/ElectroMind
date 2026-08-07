# Resources

> Load this when: you need upstream links for TESLA, ai2-kit, oh-my-batch, or
> the underlying engines.

## Upstream

- ai2-kit repository: https://github.com/chenggroup/ai2-kit
- ai2-kit on PyPI: https://pypi.org/project/ai2-kit/
- oh-my-batch: https://github.com/link89/oh-my-batch
- ai2-kit TESLA examples: `example/use-case/tesla`,
  `example/use-case/tesla-for-ec-mlp`, `example/use-case/tesla-pimd` inside
  the ai2-kit repository
- ai2-kit manuals: `doc/manual/dpdata.md`, `doc/manual/model-deviation.md`,
  `doc/manual/ase.md` inside the repository

## Engines (operated by their tool skills)

- DeepMD-kit: https://github.com/deepmodeling/deepmd-kit
- dpdata: https://github.com/deepmodeling/dpdata
- LAMMPS: https://www.lammps.org/
- CP2K: https://www.cp2k.org/
- VASP: https://www.vasp.at/

## In this repository

- `ai2kit` tool skill — data conversion, model-deviation processing,
  environment checks
- `deepmd` tool skill — training, lcurve, freeze/compress, QA
- `lammps` tool skill — classical MD, exploration MD, production MD
- `cp2k` / `vasp` tool skills — labeling DFT
- `hpc-submit` / `rsess` tool skills — submission, monitoring, recovery
- `packmol` / `structure-prep` tool skills — initial configurations

## Stability warning

All of the above are under active development. Concrete flags, output formats,
and defaults change between releases; verify with `--help` and installed
source before use, and record observed versions in the iteration manifest.

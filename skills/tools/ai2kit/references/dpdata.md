# ai2-kit dpdata Tool

> Load this when: converting dpdata datasets, checking type_map contracts,
> slicing/sampling frames, or handing data to DeepMD training.

## Concepts

- **dpdata.System / LabeledSystem.** A `System` holds coordinates and boxes for
  one composition; a `LabeledSystem` additionally carries energies/forces (and
  optionally virials) per frame.
- **deepmd/npy format.** A dpdata system directory contains `type.raw`
  (one atom-type index per atom), `type_map.raw` (element symbols in order), and
  `set.NNN/` directories holding `coord.npy`, `box.npy` (optional), `energy.npy`
  (optional), `force.npy` (optional), `virial.npy` (optional).
- **type_map is a contract.** `type_map.raw` order must match DeepMD's
  `input.json` `type_map` and the LAMMPS atom types used later. Changing it
  silently corrupts every downstream consumer.
- **Units.** Coordinates in Å, energies in eV, forces in eV/Å, virials in eV.
- **Labels are optional.** Unlabeled systems are valid for structure work; use
  `--nolabel` when reading systems that carry no energies/forces.

## Typical operations

Read one or more systems (wildcards are allowed) and convert them:

```bash
ai2-kit tool dpdata read ./workdir/iters-*/train-deepmd/new_dataset/* \
  - to_ase - write merged.xyz
```

`read` can be called multiple times in one pipeline to merge datasets; each
`read` appends its frames to the in-memory set.

## DeepMD handoff contract

Before `dp train` (owned by `deepmd`), the dataset must satisfy:

- frames present and readable (`set.NNN/coord.npy` shape (frames, natoms, 3));
- `type_map.raw` present and consistent with `type.raw` indices and the DeepMD
  `type_map`;
- `natoms` consistent between `type.raw` and the coordinate shape;
- energy/force/virial arrays, when present, match the frame count and atom
  count (no ragged shapes);
- no NaN/Inf anywhere in the loaded arrays.

Run `scripts/check_dpdata_system.py` on the system directory to verify all of
the above as one deterministic JSON verdict before handoff. For TESLA datasets,
`tesla-mlp-training` additionally pins a dataset fingerprint (frame count,
type_map, natoms, label presence) that must stay stable across updates —
`references/update.md` in that skill.

# ai2-kit ASE Tool

> Load this when: reading/writing structures through ASE, manipulating atoms
> (positions, species, supercells), or interchanging ASE and dpdata objects.

## Concepts

- **ASE Atoms.** The atomic-structure container: positions, species (symbols),
  cell, and per-atom arrays. ASE is the interchange hub between ai2-kit tools
  and other formats.
- **Formats.** ASE reads/writes many formats: XYZ, VASP POSCAR/CONTCAR, CIF,
  LAMMPS data/`dump`, PDB, and others.
- **dpdata interchange.** dpdata systems convert to ASE via
  `system.to_ase_structure()`; on the command line this is the `to_ase` chain
  step, which hands the pipeline over to the ASE tool. Converting back follows
  the reverse chain from ASE to dpdata formats.

## Typical operations

Structure round-trip through the pipeline:

```bash
ai2-kit tool dpdata read ./dp-h2o --fmt deepmd/npy - to_ase - write h2o.xyz
```

Write per-frame VASP inputs:

```bash
ai2-kit tool dpdata read ./dp-h2o --fmt deepmd/npy \
  - to_ase - write_frames "./vasp-{i-04d}/POSCAR" --format vasp
```

The ASE tool group offers its own chainable `read`/`write`-style surface;
confirm the exact subcommand names with `ai2-kit tool ase --help` before use
(drift policy: `references/versions.md`).

## Validation

- After any conversion, verify the round trip: frame count, element order, and
  cell must survive unchanged (or change exactly as intended).
- `scripts/check_dpdata_system.py` validates dpdata-side outputs; compare the
  frame count against the source trajectory and record both paths.
- Element ordering from ASE is symbolic — confirm it maps back onto the dpdata
  `type_map` order when returning to dpdata/DeepMD land.

---
name: structure-prep
description: Prepare and convert atomistic structures before calculations. Use for CIF/POSCAR/CONTCAR/XYZ/PDB/MOL/SDF/SMILES handling, supercells, slabs, surface terminations, defects, substitutions, adsorbate placement, symmetry analysis, conformer generation, and charge/multiplicity determination for molecules.
---

# Structure Preparation

Two toolchains by system type: **periodic** (crystals, slabs, defects, VASP files) → pymatgen; **molecular** (SMILES, conformers, finite molecules) → RDKit.

## Where to find what

| Situation | Go to |
|---|---|
| building anything: slabs, supercells, defects, adsorbates, conformers, conversions, database sourcing | `references/running.md` |
| slab symmetry policy, vacuum economy, structure release gate, `.research` integration | `references/surfaces.md` |
| checking a structure before/after an operation; release gates | `references/validation.md` |
| embedding fails, disordered CIFs, symprec surprises, polar slabs | `references/errors.md` |
| slab with selective dynamics | `scripts/make_slab.py` |
| place an adsorbate on a slab — enumerate distinct sites (multi-start), selective dynamics, binding distances | `scripts/place_adsorbate.py` |
| audit a generated slab/adsorbate/cluster model before engine handoff | `scripts/audit_structure.py` + `references/validation.md` |
| dopant / vacancy / interstitial: substitution, O-vacancy, subsurface dopant, single-atom site | `scripts/dope_structure.py` |
| SMILES → 3D + charge/multiplicity report | `scripts/smiles_to_xyz.py` |
| format conversion with validation summary | `scripts/convert_structure.py` |
| working examples to copy and adapt | `examples/` |
| not covered locally (pymatgen/RDKit docs, structure databases) | `references/resources.md` |

## Hard guardrails

- Never invent lattice vectors — no cell, no periodic calculation.
- Initial-structure discovery is project-local. Look only in the current project
  root/current working directory and user-explicit input paths. Do not run broad
  `find` searches over `$HOME`, `/home`, `/opt`, `/`, shared software trees, scratch
  roots, or unrelated archives. If nothing is supplied in that bounded scope, record
  that no usable initial structure was supplied and build from declared database,
  literature, manuscript, or builder assumptions.
- No molecule enters electronic-structure work without explicit charge and multiplicity (with stated origin).
- Termination, defect-site, and conformer choices are scientific decisions: enumerate and ask/justify, never randomize silently.
- Stoichiometry follows the chemical environment. For effectively fixed-valence or
  non-redox-active components under the modeled conditions, keep models
  charge-balanced and close to expected stoichiometry unless a compensating defect,
  adsorbate, or source precedent justifies otherwise. For redox-active or
  variable-valence components, non-stoichiometry, vacancies, hydroxylation, or
  element-rich terminations can be acceptable when tied to the declared synthesis,
  gas, solvent, electrochemical, or reservoir condition.
- Slab/facet/adsorbate models need a structure release gate (Miller/termination
  precedent or a labeled exploratory record, then geometry audit) before engine
  handoff; slab symmetry, tilted-`c` handling, vacuum economy, and `.research`
  integration details: `references/surfaces.md`.
- Structure-generation scripts stop at candidate structures and validation/audit
  artifacts. They must not write scheduler scripts, call `sbatch`/`qsub`, or create
  final engine input packs before structure gate acceptance. Any function that
  mutates coordinates, lattice vectors, periodicity, or atom count must not write
  `INCAR`, `KPOINTS`, `POTCAR`, `submit.sh`, or call the scheduler in the same call
  path.
- Originals preserved; derived structures to new paths; database structures carry their entry ID.

## Handoff

Periodic DFT → `vasp`. Molecular QC and biomolecular/liquid/membrane MD → the selected available engine. Materials/reactive/MLP MD → `lammps` (note unit/atom-style requirements). Report output files, formula, atom count, and every assumption.

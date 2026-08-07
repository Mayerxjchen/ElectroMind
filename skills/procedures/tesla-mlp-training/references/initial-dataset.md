# Initial Dataset

> Load this when: building the seed dataset before the first training
> iteration, or judging whether existing labels are enough to start.

## Coverage first, no fixed frame count

There is **no global fixed frame count** that defines a production-ready
initial dataset. Sufficiency is assessed by:

- configuration-space coverage: composition, phase, defects/interfaces,
  volume/strain, temperature, relevant reactive/diffusive events;
- held-out energy/force accuracy of models trained on the dataset;
- model deviation/uncertainty on unexplored regions;
- active-learning convergence over iterations;
- MD stability in production conditions;
- target physical observables (density, RDF, diffusion, ...).

50, 500, or 10000 frames are project parameters, never rules. A small
carefully sampled set can start a pilot; a production potential needs the
coverage evidence above.

## Sources

Typical initial-label routes (choose by system and availability):

- **packmol + classical MD sampling + DFT labels**: pack an equilibrated box
  (e.g. 64 H2O), run short classical MD (`lammps`) to walk the target
  temperature/volume, then label distinct sampled frames with CP2K/VASP
  (`references/label.md`).
- **AIMD labels**: run ab-initio MD and collect converged, chemically sensible
  frames.
- **Existing datasets**: convert with `ai2kit` dpdata tools; verify the
  method fingerprint and provenance before reuse.

Sampling guidance: multiple physically plausible starting models and multiple
temperatures beat a single long trajectory — coverage is the goal, not raw
frame count.

## Fingerprint at creation time

The initial dataset is created with one method fingerprint (functional, basis/
cutoff, k-points, U, spin, convergence thresholds, pseudopotentials) and
recorded in the first iteration manifest as `parent_dataset_digest`. If the
fingerprint must change later, that is a **new dataset**, not an update
(`references/update.md`).

## Validation before first training

Before TRAIN, the initial dataset must satisfy (VALIDATED for INIT):

- frames, atom types, energies, forces, and cell complete;
- `type_map` consistent with DeepMD `input.json` and LAMMPS atom types;
- no NaN/Inf; shapes consistent;
- dataset fingerprint (frames, type_map, natoms, label presence) recorded.

Run `scripts/check_dataset_fingerprint.py` against the dataset directory and
the declared fingerprint, and fix anything it flags before spending training
hours.

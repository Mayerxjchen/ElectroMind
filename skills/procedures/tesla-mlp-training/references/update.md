# UPDATE Stage (Dataset Update)

> Load this when: merging new labels into the training dataset, re-splitting
> train/validation/test, or checking that a dataset update did not break the
> fingerprint.

The UPDATE stage is executed by `ai2kit` (dpdata tool); this reference
decides the rules.

## What happens here

1. Merge the VALIDATED labels from LABEL into the training dataset.
2. Re-split train/validation/test.
3. Verify the updated dataset and record its digest.

## Fingerprint invariance

**One dataset = one method fingerprint.** Updating means appending labels
with the same method fingerprint: same functional, basis/cutoff, k-point
policy, U values, spin policy, convergence thresholds, pseudopotentials. A
method change is a new dataset, not an update — mixing fingerprints corrupts
the training signal silently.

Update also never changes:

- `type_map` order (contract for DeepMD and LAMMPS);
- natoms per system (composition is fixed within a dataset);
- units.

## Merge rules

- Only VALIDATED frames enter (`references/label.md`); failed or waived
  frames never merge.
- Dedupe against the existing dataset: frame digest collision with an
  existing frame (same coordinates/cell/type order) is a duplicate — count
  it, do not append it.
- Frame count after merge must equal previous count + newly VALIDATED frames
  (minus dedupe hits); any mismatch is an update failure.

## VALIDATED conditions (UPDATE)

- updated dataset readable (dpdata loads it);
- frame count correct (previous + new VALIDATED - duplicates);
- `type_map` unchanged;
- method fingerprint unchanged;
- no NaN/Inf introduced.

## Checks

- `scripts/check_dataset_fingerprint.py` verifies the updated directory
  against the declared fingerprint (frames, type_map, natoms, label
  presence). The fingerprint file is JSON with `method`, `frames`, `natoms`,
  `type_map`, and `labels` (`energy`/`force`/`virial` booleans); the script's
  docstring shows the schema.
- `ai2kit`'s `scripts/check_dpdata_system.py` checks structure-level
  integrity.
- `scripts/check_iteration.py` marks UPDATE `completed`/`validated` and
  echoes the manifest.

## Handoff

The updated dataset feeds the next TRAIN. Record
`updated_dataset_digest` in the iteration manifest; the next iteration's
`training_dataset_digest` must equal it (`references/iteration-manifest.md`).

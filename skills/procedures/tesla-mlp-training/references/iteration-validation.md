# Iteration Validation

> Load this when: deciding whether a stage or an iteration is scientifically
> valid, or when writing/checking VALIDATED records.

## COMPLETED vs VALIDATED

- `<stage>.done` exists => the stage **completed** (execution finished).
- `<stage>.validated` exists => the stage passed its **VALIDATED** checks.
- `*.done` never implies validity; an unvalidated stage is not promoted.

`scripts/check_iteration.py` reports the two fields per stage explicitly
(`completed` and `validated`) and never conflates them.

## Per-stage VALIDATED checklists

### INIT

- frames, atom types, energies, forces, and cell complete;
- dataset fingerprint (frames, type_map, natoms, label presence) recorded and
  consistent.

### TRAIN

- model files generated per committee member;
- lcurve sane (losses decrease and stabilize);
- no NaN in losses or outputs;
- held-out metrics recorded.

### EXPLORE

- LAMMPS terminated normally;
- zero lost atoms;
- trajectory and `model_devi.out` complete (rows == frames, finite);
- exploration conditions recorded.

### SCREEN

- model deviation parseable for every replica;
- frame mapping consistent;
- candidates valid and unique;
- candidate/selected counts recorded.

### LABEL

- DFT runs terminated normally with SCF converged;
- energies/forces complete for every VALIDATED frame;
- label contract satisfied per frame (all seven conditions:
  `references/label.md`);
- no duplicates; parser provenance recorded.

### UPDATE

- dataset readable;
- frame count correct;
- `type_map` unchanged;
- method fingerprint unchanged.

### ITERATION

- all stage validations above passed for this iteration;
- iteration manifest written with validation_status.

### FINAL

- held-out error acceptable;
- MD stability at production conditions;
- target physical observables reproduced.

## Procedure

1. After a stage's execution and parsing, run the stage's checks
   (`scripts/check_iteration.py`, tool-skill validators).
2. If all checks pass, write `<stage>.validated`.
3. If anything fails, the stage is unvalidated; fix or waive with a recorded
   reason before the iteration may proceed.
4. An iteration with any unvalidated stage must not feed the next iteration
   silently — surface it, recover (`references/recovery.md`), or stop.

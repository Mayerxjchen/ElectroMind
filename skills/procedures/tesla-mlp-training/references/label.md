# LABEL Stage (CP2K / VASP)

> Load this when: running single-point DFT labels on screened frames,
> validating per-frame labels, converting labels to dpdata, or retrying
> failed labels without duplicating frames in the dataset.

The LABEL stage is executed by `cp2k` / `vasp` (ENERGY_FORCE single points);
this reference decides what and when, including the labeling contract.

## What happens here

1. Convert each selected frame into a DFT input (coordinates + cell).
2. Run single-point energy/force calculations (CP2K `RUN_TYPE ENERGY_FORCE`
   or the VASP equivalent).
3. Validate each frame against the labeling contract.
4. Convert successful labels to dpdata via `ai2kit` and hand them to UPDATE.

## Per-frame VALIDATED contract

A labeled frame is VALIDATED only when **all** of the following hold:

1. coordinates and cell known and unambiguous;
2. DFT run terminated normally;
3. SCF converged;
4. total energy present;
5. forces present for every atom;
6. atom count and type order match the source structure;
7. label method fingerprint matches the dataset fingerprint.

`PROGRAM ENDED AT` in a CP2K log only proves the program ended — it says
nothing about scientific validity. A frame missing any condition is a failed
frame, handled explicitly (see below), never silently dropped into the
dataset.

## Retry policy: duplicate configuration handling

Retrying failed frames is normal; duplicating successful ones is not.

- Before any run, dedupe candidates against the **label manifest**: a
  per-iteration record (or the iteration manifest) of frame identity + method
  fingerprint + label status.
- Frame identity = structure content digest (coordinates+cell+type order,
  quantized) — not the file name, which changes across retries.
- A frame already labeled with the same method fingerprint is never labeled
  again, even if a later retry reruns it.
- **Label parser provenance**: record which parser/version produced each
  label set (e.g. the CP2K output parser used) so a parser change does not
  silently mix label generations; when the parser changes, re-validate
  affected frames rather than mixing.

This is enforced by the procedure (via the manifest and `label_success_count`
/ `label_failure_count`), not by the DFT code.

## VALIDATED conditions (LABEL)

- DFT runs terminated normally with SCF converged;
- energies/forces complete for every VALIDATED frame;
- failed frames counted and handled (retried or waived with a recorded
  reason);
- no duplicate frames entered the label set;
- label parser version recorded.

## Checks

- `scripts/check_iteration.py` marks LABEL `completed`/`validated`.
- Per-frame verdicts come from the DFT tool skill's parsers
  (`cp2k` / `vasp`).

## Handoff

Successful labels convert to dpdata via `ai2kit` (dpdata tool), keeping the
dataset's type_map and method fingerprint. UPDATE then merges them into the
training dataset.

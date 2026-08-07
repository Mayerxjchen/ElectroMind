# SCREEN Stage (ai2kit)

> Load this when: grading exploration frames by model deviation, selecting
> candidates for labeling, or judging whether an iteration produced useful
> candidates.

The SCREEN stage is executed by `ai2kit` (model-deviation processing); this
reference decides the strategy.

## What happens here

1. Validate each replica's `model_devi.out` (`ai2kit`'s
   `scripts/check_model_devi.py`): parseable, finite, frame count matches the
   trajectory.
2. Grade frames by force deviation with project thresholds:
   `good` below `lo`, `decent` between `lo` and `hi`, `poor` above `hi`.
3. Select candidates for labeling — typically the `decent` band plus a
   controlled number of `poor` frames for extrapolation.
4. Write the selected frames (`selected.xyz`) and record grading statistics.

## Thresholds are project parameters

`lo`, `hi`, the deviation column, and how many candidates per class enter
labeling are decided here per project and recorded in the iteration manifest
(`candidate_count`, `selected_count`). There are no global defaults; the
numbers must be justified against the system's chemistry and the models'
held-out behavior. If thresholds are drifting iteration to iteration, record
the rationale in the manifest.

## Frame mapping discipline

The grading operates on the same frame mapping validated in EXPLORE: frame `i`
of `model_devi.out` is frame `i` of the dump. Any mismatch (ragged rows, NaN,
broken steps) is a screen failure, not something to grade around.

## VALIDATED conditions (SCREEN)

- model deviation files parseable for every replica;
- frame mapping consistent (deviation rows == trajectory frames);
- candidates valid: finite values, unique frames, structure readable
  (e.g. `selected.xyz` parses with ASE);
- counts recorded in the iteration manifest.

## Checks

- `ai2kit`'s `scripts/check_model_devi.py --lo ... --hi ...` gives the
  candidate counts as JSON.
- `scripts/check_iteration.py` marks SCREEN `completed`/`validated`.

## Handoff

Selected frames go to the LABEL stage. Also keep the `good`-band statistics:
a run where nearly everything is `good` is evidence for the stopping
discussion (`references/stopping.md`).

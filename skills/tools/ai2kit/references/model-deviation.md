# Model Deviation Processing

> Load this when: parsing `model_devi.out`, grading exploration frames by
> deviation, checking frame mapping against a trajectory, or summarizing
> deviation statistics.

## What model deviation is

Model deviation is the disagreement between the predictions of several
machine-learning potential models (typically a DeepMD committee) on the same
frames. High force deviation marks frames where the models extrapolate — the
usual candidates for new DFT labels in active learning. The deviation itself is
computed by `deepmd` (e.g. `dp model-devi`); this skill only reads, validates,
and filters the produced numbers.

## model_devi.out column structure

The deviation file is produced per trajectory (typically one `model_devi.out`
per exploration replica). Column layout for `n` models:

```text
step, then for each model: max_devi_v avg_devi_v min_devi_v
                          max_devi_f avg_devi_f min_devi_f
                          max_devi_e avg_devi_e min_devi_e
```

i.e. `1 + 9 * n` columns. With a 4-model committee the file has 37 columns and
`max_devi_f` appears once per model. Some producers write a header line with
column names; treat a leading non-numeric line as a header.

## Stable parsing rules

- Row 0 of the data columns is the step; it maps 1:1 onto trajectory frames —
  frame `i` of `model_devi.out` corresponds to frame `i` of the dump file it
  accompanies (when steps are written per frame).
- Steps must be non-negative and non-decreasing; a restart or gap breaks the
  mapping and must be reported, not silently assumed.
- Every value must be finite. NaN/Inf in deviation output means a broken model
  or a corrupt file.
- Column counts must be identical on every row; a ragged file fails parsing.
- Statistics are reported per column and per quantity: max/mean/min of
  `max_devi_f` across frames, mean of `avg_devi_f`, and the same for energy.

## Grading (filtering)

The model-deviation tool grades frames by a deviation column (default
`max_devi_f`) with project-supplied thresholds:

```bash
ai2-kit tool model_devi read "./workdir/lammps/*" \
  --traj_file dump.lammpstrj --md_file model_devi.out \
  - grade --lo 0.1 --hi 0.2 --col max_devi_f \
  - dump_stats stats.tsv \
  - write selected.xyz --level decent
```

- `good`: below `lo`; `decent`: between `lo` and `hi`; `poor`: above `hi`.
- The outlier marker defaults to `2 * hi` when not given.
- The `read` step fails the chain when trajectory and deviation file frame
  counts disagree.

## Frame mapping and validation

- `scripts/check_model_devi.py` verifies readability, column layout, frame
  count, finiteness, step mapping, and summary statistics as one JSON verdict;
  pass `--lo/--hi` to also get candidate counts.
- Cross-check the deviation frame count against the source trajectory
  (expected frames) before grading — a truncated explore run changes the
  candidate set silently.

## Thresholds are project parameters

This skill records rules, not global defaults: `lo`, `hi`, the deviation
column, and how many candidates enter labeling are decided per project by
`tesla-mlp-training` (`references/screen.md` there). Never invent a "standard"
threshold on your own.

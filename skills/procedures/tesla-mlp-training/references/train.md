# TRAIN Stage (DeepMD)

> Load this when: training the model committee, checking lcurve, freezing and
> compressing graphs, or judging training quality.

The TRAIN stage is executed by `deepmd`; this reference only decides what and
when.

## What happens here

1. Verify the training dataset: fingerprint unchanged, splits sensible
   (`references/update.md`).
2. Write `input.json` (with `deepmd`) on the training dataset.
3. Train the committee — the number of models is a project decision (4 is a
   common default, not a rule).
4. Freeze/compress graphs, producing `graph.000.pb` ... `graph.NNN.pb`.
5. QA: lcurve review, held-out `dp test`, parity, coverage diagnostics.

## Decisions owned by this procedure

- when the initial dataset is enough to start training
- committee size and seed strategy
- how many models enter exploration deviation
- when training quality is acceptable for exploration

## VALIDATED conditions (TRAIN)

- model files generated (one per committee member);
- lcurve sane: training and validation loss decrease then stabilize;
- no NaN in losses or model outputs;
- held-out metrics recorded (they are the quality gate, not lcurve alone).

## Checks and summaries

- `scripts/summarize_iteration.py --lcurve` prints the lcurve summary
  (final loss, minimum validation loss).
- `deepmd`'s QA scripts produce the full verdict before models are promoted
  to exploration.
- `scripts/check_iteration.py` marks TRAIN `completed` from the done marker;
  `validated` only when the above conditions hold.

## Handoff

Exploration consumes frozen graphs plus the `type_map`. Record the model
paths and the dataset digest in the iteration manifest (`models[]`,
`training_dataset_digest`).

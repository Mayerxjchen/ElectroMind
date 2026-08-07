# oh-my-batch (omb)

> Load this when: generating batch runs for HPC stages, or running many
> near-identical jobs (replicas, per-frame DFT labels, training seeds).

oh-my-batch is the companion batch tool used by ai2-kit/TESLA workflows
(upstream: `link89/oh-my-batch`). It turns one template plus value tables
into many concrete jobs. It is documented here rather than as an independent
skill until it earns one; everything concrete must be verified against the
installed `omb --help`.

## Core concepts

- **combo** — a template (shell script with placeholders) plus a value table
  (columns of parameter values); each row of the table produces one concrete
  script.
- **batch** — the combination of a combo with its values; a batch is what you
  submit.
- **job** — one generated concrete job from a batch row (one replica, one
  label frame, one seed).

## Typical use in TESLA

```text
template (run stage for {replica} at {temperature})
  + value table (replica 0..3, temperatures)
  -> batch -> one job per row
```

Batch-generate exploration replicas, per-frame label runs, or training seeds
from the same templates in `00-config/`.

## Rules

- Generate batches from the project's own templates; never invent template
  contents from memory.
- Verify the generated job scripts (inputs, paths, modules) before
  submission — generation success is not correctness.
- Job monitoring and recovery stay with `hpc-submit`; omb only generates.
- Record the generated batch/job IDs in the iteration manifest or HPC
  records so recovery can find them.
- Drift warning: omb's flag names change; confirm with `omb --help` and the
  upstream README before scripting.

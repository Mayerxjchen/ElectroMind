# Iteration Manifest

> Load this when: writing or reading the per-iteration provenance record.

Each iteration keeps a minimal machine-readable manifest,
`iteration-manifest.json`, in the iteration directory. It is TESLA's own
provenance — not a research DAG, not an ElectroMind overlay. It survives
restarts and makes handoffs auditable.

## Schema

| Field | Type | Meaning |
|---|---|---|
| `iteration_id` | string | e.g. `iter-1` |
| `parent_dataset_digest` | string | digest of the dataset this iteration's TRAIN consumed |
| `training_dataset_digest` | string | digest of the dataset TRAIN actually used (equals previous `updated_dataset_digest`) |
| `models[]` | array of strings | paths of the trained models (e.g. `20-workdir/iter-1/01_train/graph.000.pb`) |
| `exploration_conditions[]` | array of objects | per-replica conditions: temperature, pressure, steps, seed, replica id |
| `candidate_count` | integer | frames graded as candidates by SCREEN |
| `selected_count` | integer | frames selected for labeling |
| `label_success_count` | integer | frames labeled and VALIDATED |
| `label_failure_count` | integer | frames that failed labeling (retried/waived) |
| `updated_dataset_digest` | string | digest of the dataset after UPDATE (null until UPDATE validated) |
| `validation_status` | string | one of `pending`, `partial`, `validated`, `failed` |

## Rules

- Write/refresh the manifest at every stage boundary — never only at the end.
- Digests are deterministic content hashes over the dataset's identifying
  content (type_map, natoms, frame count, label presence, method fingerprint
  string). Two datasets with the same digest are interchangeable; any change
  in those fields changes the digest.
- `label_success_count + label_failure_count` must equal `selected_count`
  (after dedupe), or the manifest itself is wrong.
- `validation_status` is `validated` only when every stage's
  `*.validated` marker exists (`references/iteration-validation.md`).
- The manifest is read and echoed by `scripts/check_iteration.py`.

## Example

```json
{
  "iteration_id": "iter-1",
  "parent_dataset_digest": "sha256:1c2f...",
  "training_dataset_digest": "sha256:1c2f...",
  "models": [
    "20-workdir/iter-1/01_train/graph.000.pb",
    "20-workdir/iter-1/01_train/graph.001.pb",
    "20-workdir/iter-1/01_train/graph.002.pb",
    "20-workdir/iter-1/01_train/graph.003.pb"
  ],
  "exploration_conditions": [
    {"replica": 0, "temperature_k": 300, "pressure_bar": 1, "steps": 100000, "seed": 11}
  ],
  "candidate_count": 120,
  "selected_count": 40,
  "label_success_count": 36,
  "label_failure_count": 4,
  "updated_dataset_digest": "sha256:9a4e...",
  "validation_status": "validated"
}
```

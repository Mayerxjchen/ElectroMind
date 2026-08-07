# Recovery

> Load this when: an HPC job failed, was killed, or was interrupted, and the
> iteration must resume.

## Principles

- **Never resubmit blindly.** Read scheduler state, logs, and stage markers
  first; identify the earliest incomplete stage; resume from there.
- **TESLA state is the source of truth**: stage done markers, `.validated`
  records, iteration manifest, dataset digests, model files, job records.
- Completing a stage twice must be harmless: label dedupe
  (`references/label.md`) and dataset update rules
  (`references/update.md`) make re-running idempotent for data; re-running
  compute is only a waste of HPC hours, never a corruption.

## Resume procedure

1. **Assess**: run `scripts/check_tesla_project.py` and
   `scripts/check_iteration.py` on the project; read the iteration manifest
   and the failing job's logs.
2. **Classify**: scheduler failure (queue, walltime, node), application
   failure (input, convergence, crash), or infrastructure failure (network,
   filesystem).
3. **Fix the root cause**: consult the owning tool skill's error reference
   (`deepmd`, `lammps`, `cp2k`, `vasp`) and `hpc-submit` job recovery
   guidance. One fix at a time.
4. **Resume from the earliest incomplete stage**: rerun only what is not
   `completed`; never restart whole validated stages.
5. **Re-validate**: after resume, re-run the stage checks and update the
   manifest (`validation_status`, counts, digests).

## HPC-specific recovery

- Route all resubmission through `hpc-submit` (and `rsess` for persistent
  remote shell state). Read the target cluster conventions first.
- Use resubmission-safe job patterns (checkpointing, restartable MD, per-job
  logs) from the start so recovery is cheap.
- Monitor resumed jobs to completion; do not assume a resubmit landed.

## Failed labels

Failed label frames (`label_failure_count`) are retried or waived with a
recorded reason. Retry never duplicates frames already in the label set or
dataset: dedupe by structure digest + method fingerprint
(`references/label.md`).

## Restarting a full iteration

If an iteration directory is corrupted beyond repair, recreate it from the
manifest and the parent dataset, then resume from its earliest stage. The
manifest is the contract; never hand-reconstruct digests or counts — recompute
them with the check scripts.

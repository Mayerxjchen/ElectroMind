# EXPLORE Stage (LAMMPS)

> Load this when: running exploration MD with the committee, producing
> trajectories and model deviation, or judging whether exploration sampled
> the intended conditions.

The EXPLORE stage is executed by `lammps`; this reference decides what and
when.

## What happens here

1. Build LAMMPS inputs from templates (`00-config/`) with the frozen graphs as
   `pair_style deepmd` models.
2. Run production-style MD at the exploration conditions.
3. Record per-replica trajectory dumps and `model_devi.out` (model deviation
   produced via DeepMD's deviation machinery; parsing/filtering is
   `references/screen.md` and the `ai2kit` skill).

## Parameters are project decisions

Temperature(s), number of replicas, number of steps, thermostat, pressure
control, and sampling stride are project parameters owned here — they are
chosen to probe the target phase space, not copied from an example. Record
them as `exploration_conditions[]` in the iteration manifest.

- Replicas: several independent replicas with different seeds give honest
  deviation statistics; one trajectory may under-sample.
- Temperatures: explore at and beyond the target conditions so the committee
  exposes extrapolation where production MD will run.
- Stride: dense enough for candidate selection, sparse enough to be
  affordable.

## Frame mapping

Every `model_devi.out` row maps 1:1 onto a trajectory frame: frame `i` of the
deviation file corresponds to frame `i` of its dump file. Steps must be
non-decreasing; restarts that break the mapping must be reported
(`ai2kit`'s `scripts/check_model_devi.py`).

## VALIDATED conditions (EXPLORE)

- LAMMPS terminated normally (not killed, not restarted mid-write);
- zero lost atoms;
- trajectory dumps complete for the declared step count;
- `model_devi.out` complete: row count matches trajectory frames, all finite;
- conditions recorded in the iteration manifest.

## Checks

- `scripts/check_iteration.py` marks EXPLORE `completed`/`validated`.
- `ai2kit`'s `scripts/check_model_devi.py` validates each replica's deviation
  file before screening.

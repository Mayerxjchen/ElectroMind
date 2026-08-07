# fixtures (placeholders)

This directory will hold **tiny synthetic fixtures** for logic acceptance of
the TESLA chain — never real data:

- fake init dataset: a few dpdata frames with `type.raw`, `type_map.raw`,
  `set.000/` arrays (or a script that generates them)
- fake `lcurve.out` for `summarize_iteration.py`
- fake `model_devi.out` files for `check_iteration.py` and
  `scripts/summarize_iteration.py`
- tiny CP2K-style success/failed outputs for the label parser path
- fake scheduler states for the recovery path

Purpose: verify the INIT -> TRAIN -> EXPLORE -> SCREEN -> LABEL -> UPDATE ->
VALIDATED logic chain without running DeepMD/LAMMPS/CP2K. The real water64
scientific acceptance runs real calculations elsewhere.

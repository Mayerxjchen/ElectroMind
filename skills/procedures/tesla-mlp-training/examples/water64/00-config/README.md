# 00-config (placeholders)

This directory holds **template descriptions** for the shared inputs of the
water64 project. No real templates or data are committed.

Expected contents once populated (project-owned files, not skill artifacts):

- DeepMD `input.json` template (descriptor + fitting, type_map O,H,H)
- LAMMPS input templates (classical MD, exploration MD with `pair_style
  deepmd`, production MD)
- CP2K input template (RUN_TYPE ENERGY_FORCE with the project method
  fingerprint)
- Slurm job script templates

Every template parameter that depends on the system (temperature, pressure,
steps, thresholds, seeds) is a project decision recorded in the iteration
manifest, not a skill default.

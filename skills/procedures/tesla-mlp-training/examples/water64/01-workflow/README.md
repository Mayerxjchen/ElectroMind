# 01-workflow (placeholders)

This directory holds **strategy-script descriptions** for the water64 project.
No real scripts or data are committed.

Expected contents once populated:

- a per-iteration driver script (an `iter-basic-dp-lammps-cp2k`-style
  strategy, adapted to this project's conditions)
- helper scripts that copy templates from `00-config/` into the iteration
  directory and write stage done markers

The driver is project-owned code; `ai2kit` never generates or edits it. The
top-level `run.sh` of the project walks iterations by calling these strategy
scripts.

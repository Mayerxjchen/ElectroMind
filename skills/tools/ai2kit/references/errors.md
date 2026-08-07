# ai2-kit Troubleshooting

> Load this when: an `ai2-kit` command fails, a parse fails, a dependency is
> missing, or trajectory/deviation frame counts disagree.

| Symptom | Likely cause | Fix |
|---|---|---|
| `ai2-kit: command not found` | package not installed or not on PATH | `pip show ai2-kit`; install into the active environment; check `which ai2-kit` |
| `ai2-kit: error: no such subcommand` | CLI drift (subcommand renamed/removed) | `ai2-kit --help`, `ai2-kit tool --help`; adapt to current surface; record version |
| unknown flag on a tool subcommand | CLI drift | `ai2-kit tool <name> --help`; the installed version wins over this skill's examples |
| `dpdata` `read` cannot parse a directory | wrong `--fmt`, missing `type.raw`/`type_map.raw`, ragged arrays | verify format string; run `scripts/check_dpdata_system.py` to localize the defect |
| chain fails at `model_devi` `read` | trajectory and `model_devi.out` frame counts differ | compare dump frame count vs deviation rows; re-run explore or re-map steps |
| `model_devi.out` has ragged/odd columns | wrong producer version or interleaved logs | inspect first lines; validate with `scripts/check_model_devi.py`; regenerate if needed |
| NaN/Inf in deviation or dataset arrays | broken model, corrupt file, failed label | re-check the producing stage; never propagate NaN frames into a dataset |
| `ImportError: numpy` / missing module | environment incomplete | install the dependency in the active env; rerun `scripts/check_ai2kit.py` |
| `to_ase` fails on a frame | element symbols unresolved (missing type_map) | fix `type_map.raw`; element order is part of the contract |
| script reports `degraded` | binary present but version/features incomplete | read the JSON `errors`/`warnings`; fix the listed gaps, or record a waiver |

## Debug order

1. Check the environment: `scripts/check_ai2kit.py` JSON verdict.
2. Check the data: `scripts/check_dpdata_system.py` on the involved system dir.
3. Check the deviation file: `scripts/check_model_devi.py` on the involved
   `model_devi.out`.
4. Check frame mapping: dump frame count vs deviation rows vs expected frames.
5. Check the CLI surface: `--help` on the exact subcommand being used.
6. Only then change inputs — one fix at a time, and re-run the validator.

Most failures are drift or data-contract failures, not tool bugs. Do not
reinvent a fix when the validator already names the broken artifact.

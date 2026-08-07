# ai2-kit Versions and Compatibility

> Load this when: checking whether ai2-kit is installed and compatible, or
> handling CLI drift between releases.

## Compatibility strategy

`ai2-kit` changes fast; the working policy is
"stable concepts + current source inspection + version-aware validation":

1. Run `scripts/check_ai2kit.py` first — one JSON verdict covering binary,
   import, version, required subcommands, and dpdata/ASE/model-deviation
   features. A missing installation is reported as `missing` with exit code 0.
2. Verify any concrete CLI claim at use time:
   `ai2-kit --help` -> `ai2-kit tool --help` -> `<subcommand> --help`.
3. When help output disagrees with this skill's examples, the installed
   version wins. Record the observed version and the diff in the run notes.
4. Keep the observed version with every artifact this skill hands off
   (`ai2-kit --version` or `pip show ai2-kit`), so later drift is diagnosable.

## Version checks

```bash
ai2-kit --version
pip show ai2-kit
ai2-kit --help          # top-level groups
ai2-kit tool --help     # tool-group subcommands
```

- Upstream supports Python 3.10-3.12; run the checks in the environment that
  actually has `dpdata` and ASE installed.
- The Python package is importable as `ai2_kit`; when the CLI is absent but the
  module is present, report the installation as degraded (CLI is the primary
  surface).

## CLI drift handling

- **Unknown subcommand** -> likely drift: print the help surface, then inspect
  the installed source. Locate it with
  `python -c "import ai2_kit, inspect; print(inspect.getfile(ai2_kit))"`.
- **Changed flag names** -> use the current `--help` output; do not patch the
  command from memory.
- **Changed output formats** -> re-run the `scripts/check_*` validators and
  adapt parsing to the observed columns.
- **Missing optional features** (no `dpdata`/ASE installed) -> degraded
  verdict, not a workflow failure: note it and route the missing capability to
  the environment owner.
- Never hardcode a flag or column layout from an older release into new runs
  without a `--help` check first.

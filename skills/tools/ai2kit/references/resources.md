# ai2-kit Upstream Resources

> Load this when: you need the upstream repository, manuals, examples, or the
> official TESLA build skill.

## Repository and install

- Repository: https://github.com/chenggroup/ai2-kit (MIT license)
- PyPI: https://pypi.org/project/ai2-kit/ (`pip install ai2-kit`)
- Supported Python: 3.10-3.12
- Companion batch tool: https://github.com/link89/oh-my-batch (used by TESLA
  workflows; see `tesla-mlp-training` for its role there)

## Manuals

The upstream repository keeps one manual per tool under `doc/manual/`, e.g.
`doc/manual/dpdata.md`, `doc/manual/model-deviation.md`, `doc/manual/ase.md`.
Browse them from the repository tree
(https://github.com/chenggroup/ai2-kit/tree/main/doc/manual) — the manuals are
the authoritative wording for tool behavior; this skill only keeps stable
concepts and drift policy.

## Examples

- `example/use-case/tesla` — the canonical Train-Explore-Screen-Label
  active-learning workflow example
- `example/use-case/tesla-for-ec-mlp` — TESLA for electrolyte MLP training
- `example/use-case/tesla-pimd` — TESLA variant using PIMD

The examples show the upstream directory conventions
(`00-config/`, `01-workflow/`, workdir, `run.sh`) that
`tesla-mlp-training` builds on.

## Official build skill

- `build-tesla` — the skill bundled inside the upstream repository that
  generates TESLA workflow code from the examples. Note that the upstream
  skill explicitly does not require actually executing the generated code;
  this repository's `tesla-mlp-training` skill is the real-execution
  counterpart (monitoring, parsing, validation, recovery, stopping).

## Stability warning

`ai2-kit` is under active development: subcommands, flags, and output formats
change between releases. Verify every concrete command with `--help` and the
installed source before use, and record the observed version
(`references/versions.md`).

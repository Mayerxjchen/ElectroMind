# Running Packmol

> Load this when: executing the packmol generation chain — preflight, input validation, input build, and the Packmol run itself.

## Execution sequence

1. **Resolve scientific inputs** — component identity/count, one single-molecule
   or ion XYZ per component, formal charges for ionic components, target density
   **or** fixed dimensions, periodic versus non-periodic mode, tolerance, paths,
   and system name. Do not invent or silently default scientific values; stop
   with an exact missing-input report when automation cannot ask.
2. **Write the task manifest** — `packmol-task.json` from the schema in
   `references/task-manifest.md`.
3. **Preflight + input validation** — call
   `preflight.py --workdir <dir>`, then
   `validate_manifest.py <task.json> --output <normalized.json>`. Continue only
   when both commands exit zero and emit PASSED `JSON result` records named
   `packmol_preflight` and `packmol_inputs`. Do not install missing software or
   repair invalid chemistry by guessing.
4. **Generate and execute Packmol** — call
   `build_packmol_input.py <normalized.json>` and require the
   `packmol_input_generated` result record. Execute Packmol with explicit input
   redirection, combined log capture, timeout, and exit-code preservation. Keep
   failed attempts. For periodic systems use the loaded PBC rules
   (`references/packmol-pbc.md`); for non-periodic work omit PBC. Tool Result
   failures must trigger troubleshooting guidance (`references/packmol-troubleshooting.md`)
   before a controlled retry.
5. **Validate, QC, and deliver** — see `references/validation.md`.

## Result records

Every step emits a named JSON result record; result records are never replaced
with prose. All five are required for completion:

| Record | Emitted by |
|---|---|
| `packmol_preflight` | `preflight.py` |
| `packmol_inputs` | `validate_manifest.py` |
| `packmol_input_generated` | `build_packmol_input.py` |
| `packmol_execution` | `validate_packmol_result.py` (exit code from the Packmol run) |
| `packmol_structure_qc` | `qc_structure.py` |

## Reference routing

Read references only when their condition applies:

- Periodic packing: read `references/packmol-pbc.md` before generating Packmol
  input and `references/pbc-qc-pattern.md` before QC.
- Mixtures, electrolytes, salts, solvents, or ions: read
  `references/packmol-mixture.md` before resolving composition.
- Interpreting Packmol version, success markers, or constraint violations: read
  `references/packmol-official.md`.
- Failed, timed-out, hanging, empty, or overlapping results: read
  `references/packmol-troubleshooting.md` before one controlled retry.

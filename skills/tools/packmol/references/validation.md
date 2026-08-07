# Validating Packmol Results

> Load this when: validating the Packmol execution, running structure QC, or deciding the completion status.

## Validation step

Call `validate_packmol_result.py <normalized.json> --exit-code <code>` and
require the `packmol_execution` result record. Then call
`qc_structure.py <normalized.json>` and require the `packmol_structure_qc`
result record.

## Report items

Report the minimum-image intermolecular result, gross-overlap verdict,
independent tolerance compliance, closest pair, atom count, composition, charge,
box, density, software version, and source paths.

## Deliverables

Return the manifest, templates, input, log, packed XYZ, and QC report. Set
`preparation_stage` to `"packed"`; the output is not simulation-ready or
production-ready and still needs cell/topology assignment, minimization, and
equilibration.

## Completion criteria

All five named result records (`packmol_preflight`, `packmol_inputs`,
`packmol_input_generated`, `packmol_execution`, `packmol_structure_qc`) are
required. A WARNING QC may complete with warnings. Missing results yields
`incomplete`; FAILED execution or QC yields `failed`. Never replace missing JSON
results with prose.

# Packmol Task Manifest

> Load this when: writing or validating `packmol-task.json` before generating Packmol input.

## Schema

Create `packmol-task.json` from this exact schema, replacing example values:

```json
{
  "schema_version": 1,
  "system_name": "system",
  "components": [{
    "name": "H2O",
    "template_path": "~/water.xyz",
    "template_origin": "provided",
    "count": 64,
    "formal_charge_e": 0,
    "molar_mass_g_mol": null
  }],
  "box": {
    "periodic": true,
    "dimensions_A": null,
    "target_density_g_cm3": 1.0
  },
  "packmol": {
    "tolerance_A": 2.0,
    "seed": null,
    "input_path": "~/system.inp",
    "log_path": "~/packmol.out",
    "output_path": "~/system.xyz"
  },
  "provenance": {
    "confirmed_fields": [],
    "defaulted_fields": []
  }
}
```

## Field rules

- `template_origin` is `provided`, `existing`, or `generated`. Record every
  scientific field under `confirmed_fields` or `defaulted_fields`; defaults must
  be explicitly accepted.
- Create a template only when identity and geometry are unambiguous. Generated
  multi-atom templates require an explicitly supported validator; otherwise stop.
- Specify exactly one of `dimensions_A` and `target_density_g_cm3`. A
  non-neutral system requires an explicitly confirmed net-charge policy.

## Density-derived box

For a density-derived cubic box, validation uses
`M_sum = Σ(N_i M_i)`, `V_A3 = (M_sum / N_A / rho) × 10^24`, and
`L_A = V_A3^(1/3)`, with `N_A = 6.02214076 × 10^23 mol^-1`. Never use solvent
mass alone.

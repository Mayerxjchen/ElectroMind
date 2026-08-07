# Slab, Surface, and Vacuum Policy

> Load this when: building or reviewing slab/facet/adsorbate/cluster models, choosing terminations or vacuum, or integrating structure generation with `.research` workflows.

## Slab symmetry policy

Slab top/bottom symmetry is useful when it preserves the intended surface chemistry
at reasonable cost, but it is not mandatory. If symmetry would force the wrong
termination, stoichiometry, adsorbate placement, or an oversized model, use an
asymmetric slab and record top/bottom terminations, polarity/dipole risk, fixed
layers, vacuum, and any downstream electrostatic correction.

Slab cells should normally keep the vacuum/surface-normal `c` vector perpendicular
to both `a` and `b` (`alpha` and `beta` near 90 deg). If a pymatgen-generated or
converted slab has a noticeably tilted `c`, do not first hard-rotate or
orthogonalize the finished slab. Re-check whether the cut used the intended
conventional cell and pymatgen
`SlabGenerator(..., primitive=False, max_normal_search=...)`, then verify the Miller
cut, slab normal, wrapping, and vacuum estimate before engine handoff.
`get_orthogonal_c_slab()` is an explicit fallback only when an orthogonal `c` cell is
needed and the symmetry-breaking risk is recorded.

## Vacuum economy

Vacuum is part of the model and the cost review. For large lateral cells or systems
with vacuum in two or three directions, do not keep 15-25 Å by habit; reducing an
already noninteracting vacuum direction to about 10 Å is often the right DFT
economy choice when periodic-image interactions, dipoles, charged-cell corrections,
and the target property remain acceptable. Record the reduced-vacuum rationale and
any convergence/limitation note. When using `audit_structure.py`, set the relevant
`--min-vacuum` or `--min-vacuum-adsorbate` threshold explicitly for the accepted
economy case instead of ignoring a default lower-bound failure.

## Structure release gate

Slab/facet/adsorbate models need a structure release gate before engine handoff:
literature/precedent for Miller index and termination where available, or a labeled
exploratory/no-precedent-found record for niche systems, then numerical geometry
audit of slab dimensions, `c`-axis orthogonality, vacuum lower/upper bounds,
computational economy, closest contacts with element-pair covalent-radius
thresholds/margins, adsorbate-surface distances, and periodic-image separation.

## `.research` workflow integration

Structure-generation scripts stop at candidate structures and validation/audit
artifacts. They must not write scheduler scripts, call `sbatch`/`qsub`, or create
final engine input packs before structure gate acceptance. Any function that
mutates coordinates, lattice vectors, periodicity, or atom count must not write
`INCAR`, `KPOINTS`, `POTCAR`, `submit.sh`, or call the scheduler in the same call
path. Split mixed helpers such as `generate_case()` into a structure-only function
and a separate engine-input function that starts from a reviewed structure. In
`.research` workflows, run the `research-orchestrator` skill's
`scripts/check_structure_generator_boundary.py --forbid-engine-inputs` on such
scripts before accepting the structure-modeler task.

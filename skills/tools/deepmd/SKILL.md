---
name: deepmd
description: DeePMD-kit and Deep Potential Molecular Dynamics workflows. Use for dpdata dataset conversion from VASP/CP2K, DeepMD input.json setup, dp train/freeze/compress/test, DP descriptor PCA/t-SNE dataset-distribution visualization, DP model deviation, DPLibrary reuse checks, and LAMMPS DPMD deployment.
---

# DeePMD-kit / DPMD

Deep Potential Molecular Dynamics uses a trained DP model to provide energies and forces during MD. The MD workflow is the same statistical sampling problem as AIMD; the force provider changes from DFT to the learned potential.

## Where to find what

| Situation | Go to |
|---|---|
| prepare dpdata datasets, write `input.json`, train/freeze/compress/test, run LAMMPS DPMD | `references/running.md` |
| scheduler/job script for `dp train`, GPU training, `dp test`, or DPMD deployment | activate `hpc-submit` (its `SKILL.md`); read the target `~/.cluster-agents.md` before writing the script |
| decide whether a DP model is usable, read `lcurve.out`/`dp test`, model-deviation thresholds, or read the automatic DPMD handoff verdict | `references/validation.md` |
| visualize dataset coverage/distribution with short DPA1 descriptors, PCA, or t-SNE | `references/dataset-embedding.md` |
| run the default one-chain DeepMD workflow: `dp train` -> lcurve plot -> `dp freeze` -> `dp test` -> parity plots -> DFT train/val/test PCA -> QA verdict | `scripts/run_deepmd_chain.py`; see `references/running.md` |
| produce or debug individual post-training diagnostics | `scripts/plot_deepmd_postprocess.py`, `scripts/deepmd_descriptor_pca.py`, `scripts/check_deepmd_qa.py` |
| training fails, NaN loss, bad metrics, type-map mismatch, MD instability | `references/errors.md` |
| DeepMD docs, DP-GEN, DPLibrary, related MLP programs | `references/resources.md` |
| working examples to copy and adapt | `examples/` |

## Hard guardrails

- The training distribution must cover the production task: composition, phase, defects/interfaces, volume/strain, temperature, and relevant reactive/diffusive events.
- No fixed frame count universally defines a production-ready potential.
  Dataset sufficiency is assessed using: configuration-space coverage,
  held-out energy/force accuracy, model deviation/uncertainty,
  active-learning convergence, MD stability, target physical observables.
  50/500/10000 frames are project parameters, not global hard guardrails;
  record any deliberate small-set pilot as an explicit non-production exception.
  Initial-dataset design and active-learning strategy (when to start collecting,
  per-round selection counts, model-deviation thresholds, stopping criteria) is owned
  by `tesla-mlp-training`; this skill owns the mechanics of converting, training,
  validating, and deploying DeepMD models.
- For high-temperature diffusion, transport, or reactive MD work, include training
  frames at temperatures at least as high as the final DPMD temperature;
  low-temperature-only AIMD gives a narrow potential-energy surface.
- One dataset means one DFT method fingerprint: functional, ENCUT/basis, k-point policy, U values, spin policy, convergence thresholds, and pseudopotential family.
- The `type_map` order is a contract. It must match dpdata output and LAMMPS atom types.
- Production DPMD requires validation outside the training frames: held-out error,
  learning-curve review, parity plots, dataset coverage checks, physics checks, and
  short stability tests. Model deviation is available as an uncertainty monitor
  (`references/validation.md`); when to run a committee model-deviation monitor is an
  active-learning strategy choice owned by `tesla-mlp-training`.
- Default DeepMD execution is chained, not interactive. After DFT label sources are
  identified, proceed through conversion/splitting, `dp train`, learning-curve plot,
  `dp freeze`, held-out `dp test`, parity plots, DFT-all descriptor PCA, and the QA
  verdict without pausing between phases. Stop only for a failed command, missing
  required data, an unresolved scientific choice, or a long/expensive DPMD submission
  that has not already been approved.
- Dataset PCA/t-SNE maps are coverage diagnostics only. They can reveal missing or duplicated regions, but they do not replace `dp test`, model deviation, or physics validation.
- Before LAMMPS DPMD handoff or report use, run the fixed chain or create the fixed
  DeepMD QA package:
  `deepmd_lcurve_energy_force_lr.png`, `deepmd_dp_test_energy_parity.png`,
  `deepmd_dp_test_force_parity.png`, `deepmd_dp_test_force_residual_hist.png`,
  `deepmd_descriptor_pca_dft_all.png`, `postprocess_summary.json`, and
  `deepmd_descriptor_pca_dft_all/summary.json`. Run `scripts/check_deepmd_qa.py`
  against the package and do not treat the model as handoff-ready until the automatic
  verdict passes or a visible waiver/limitation is recorded.
- The descriptor PCA for the fixed QA package is run over all compatible DFT-labeled
  `train`, `val`, and `test` frames by default. DPMD trajectory overlays are useful
  follow-up diagnostics, but they do not replace the DFT-all split coverage map.
- Scientific observables come from equilibrated production trajectory segments only; use `references/knowledge/molecular-dynamics.md` for MSD/RDF/VACF/free-energy interpretation and `references/knowledge/machine-learning-potentials.md` for MLP-wide principles.

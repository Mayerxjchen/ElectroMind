# Stopping the Active-Learning Loop

> Load this when: deciding whether another iteration is needed or the loop
> can stop.

## The stopping condition

The loop stops when **both** of the following hold, **together**:

1. **Exploration uncertainty is low**: consecutive iterations produce few or
   no high-deviation candidates (the good band dominates the grading; selected
   counts shrink toward zero without a coverage explanation).
2. **Physics validation passed**: held-out error acceptable, MD stability at
   production conditions, and target physical observables reproduced.

One without the other is not enough:

- low uncertainty but failed physics => the model is confidently wrong;
  investigate coverage and method before more iterations;
- good physics but persistent high uncertainty => the potential may be fine
  for the validated conditions but unvalidated elsewhere; either extend
  validation scope or continue exploring.

## No fixed iteration count

There is no default number of iterations. Stopping is an evidence-based
decision recorded in the iteration manifest (`validation_status`) and the
final validation report. A few iterations on a well-covered initial dataset
can be enough; a hard system can take many.

## Evidence to assemble

- model deviation statistics over the last iterations (mean/max of
  `max_devi_f`, candidate counts per iteration);
- held-out `dp test` metrics (energy/force error) from the latest models;
- MD stability: no unphysical events (lost atoms, exploding energies) at
  production conditions;
- physics observables: density, RDF, diffusion coefficient, or whatever the
  target defines;
- the final dataset digest and fingerprint (method unchanged since INIT).

## Final validation (FINAL)

Before declaring the potential usable:

- held-out error acceptable (`deepmd` QA verdict);
- MD stability at production conditions (`lammps`);
- target physical observables reproduced;
- waivers/limitations recorded visibly.

Declare the potential "first usable" only after FINALE passes; anything
earlier is a pilot model (`references/initial-dataset.md`).

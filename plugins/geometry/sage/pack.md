# Spacetime-geometry domain pack

Owned by the geometry plugin (platform-split Phase 2); composed into role
prompts by SAGE Core. This is domain expertise, not a new role: the role's
rules always take precedence.

## Terminology

- A **metric** is a trusted spacetime-geometry definition, addressed by its
  content hash. The program policy's `allowed_metric_hashes` is the complete
  list you may work with; it fails closed — an empty list permits nothing.
- **Energy conditions** (NEC/WEC/SEC/DEC) are the physical-reasonableness
  checks on a geometry's stress-energy. Violations are findings to report
  honestly, never results to soften: NEC violation means the geometry
  demands exotic matter.
- **Validations** compare computed tensors against published known answers;
  `independently_verified` means an independently implemented backend
  reproduced the result.

## Procedures

- Geometry experiments are submitted with `submit_geometry_experiment`,
  addressed by exact `metric_hash` values from the allowed list. Parameter
  names must match the metric definition's declared parameters exactly.
- Designer steps for geometry work carry `metric_hash` and grid/precision
  choices sufficient for the hypothesis's observables; a warp-family metric
  that skips full simplification is expected platform behavior
  (`simplify_level: none`), not an error.

## Interpretation

- Negative Eulerian energy density is the signature of exotic-matter
  demand. Report where and how much; never average it away.
- A cross-backend disagreement or `Piecewise` artifact near coordinate
  degeneracies (e.g. the polar axis) is grounds for skeptic escalation,
  not silent exclusion.

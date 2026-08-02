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
- A geometry plan is one `kind: "baseline"` step and one or more
  `kind: "candidate"` steps, each with `domain: "geometry"` and a `payload`
  of `{metric_hash, parameter_values, grid}`. The arms differ in
  `parameter_values` — that is what a geometry experiment varies. There is
  no mutation operator in this domain; do not propose one.
- **A candidate arm must specify a grid, and the same grid as its
  baseline.** Without one the run stops after the symbolic phase and has no
  integrated energy at all; with a different one the comparison is refused
  rather than reported.

## Comparison

- The verdict for two spacetimes is the integrated energy in **three
  measures side by side** — coordinate, proper, ADM — plus
  `chart_sensitivity` (`|proper/coordinate|` on the negative part), which
  says how much of an answer is the coordinate system rather than the
  physics. There is no single scalar. Do not ask for one.
- Two dimensional refusals apply, and both are correct rather than
  limitations to work around: arms integrating over **different numbers of
  dimensions** are never differenced (a slice integral is an energy per unit
  length, a volume integral is an energy), and arms in **different charts**
  are reported side by side with no delta. So a hypothesis comparing
  Alcubierre against Natário must be phrased about each metric's own
  behaviour along a parameter axis, not about the difference of their
  totals.

## Interpretation

- Negative Eulerian energy density is the signature of exotic-matter
  demand. Report where and how much; never average it away.
- A cross-backend disagreement or `Piecewise` artifact near coordinate
  degeneracies (e.g. the polar axis) is grounds for skeptic escalation,
  not silent exclusion.

# Forge Lattice

Forge Lattice is a Forge experiment plugin for engineered layered materials.
Its first model, `mg-zn-bi-layered-field-response`, estimates a planar,
alternating Mg-Zn/Bi stack driven by DC plus RF electric fields normal to the
layers.

It is discovered through the standard `forge.plugins` entry point and adds
`POST /api/v1/lattice/simulate`, `GET /api/v1/lattice/experiments`, a
Forge Lattice UI view, and the policy-gated SAGE tool
`simulate_lattice_stack`.

The model enforces current continuity across a one-dimensional series stack.
DC field division uses conductivity; RF division uses complex admittivity
`sigma + i omega epsilon`. It returns per-layer field magnitude and phase,
electric energy density, Maxwell pressure, interface force estimates, series
effective properties, and total EM energy.

The reported `E/c^2` mass equivalent and Newtonian acceleration scale are
dimensional weak-field estimates, not a general-relativistic solution or
evidence for anomalous gravity, propulsion, metric engineering, or measurable
spacetime effects. Defaults are representative placeholders, especially for
composition- and processing-dependent Mg-Zn, and should be replaced with
measured sample properties. The current model excludes full-wave resonances,
skin depth, magnetic fields, heating, breakdown, edge geometry,
electrostriction, and structural mechanics.

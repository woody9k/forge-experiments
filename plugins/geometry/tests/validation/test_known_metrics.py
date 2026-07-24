"""Scientific validation: every bundled metric must reproduce its known
results.  Tolerances: symbolic checks are exact (tolerance 0); numeric
spot-checks use relative tolerance 1e-8 (see forge_validation.suites.NUM_RTOL).
"""

import pytest

from forge_domain.entities import ValidationStatus
from forge_validation import run_validation_suite

pytestmark = pytest.mark.validation

FAMILIES = ["minkowski", "schwarzschild", "alcubierre", "natario"]


@pytest.mark.parametrize("name", FAMILIES)
def test_known_answer_suite_passes(geometries, name):
    pm, geo = geometries(name)
    results = run_validation_suite(pm, geo, experiment_id=f"pytest-{name}")
    assert results, "suite produced no results"
    failures = [
        f"{r.validation_type}: expected {r.expected!r}, got {r.computed!r} "
        f"(residual={r.residual}, evidence={r.evidence})"
        for r in results if r.status != ValidationStatus.PASSED
    ]
    assert not failures, "\n".join(failures)


def test_alcubierre_flat_when_velocity_zero(geometries):
    """v = 0 must reduce Alcubierre to Minkowski exactly."""
    import sympy as sp
    pm, _ = geometries("alcubierre")
    g0 = pm.matrix.subs(pm.params["v"], 0)
    assert sp.simplify(g0 - sp.diag(-1, 1, 1, 1)) == sp.zeros(4, 4)


def test_schwarzschild_asymptotically_flat(geometries):
    """g → diag(−1, 1, r², r² sin²θ) as r → ∞ (coordinate flatness)."""
    import sympy as sp
    pm, _ = geometries("schwarzschild")
    r = next(c for c in pm.coords if c.name == "r")
    assert sp.limit(pm.matrix[0, 0], r, sp.oo) == -1
    assert sp.limit(pm.matrix[1, 1], r, sp.oo) == 1


def test_alcubierre_energy_conditions_violated_on_grid(geometries):
    """Full numeric path: metric + Einstein tensor on a grid through the
    bubble wall must yield confirmed NEC and WEC violations."""
    import numpy as np
    from forge_domain.entities import GridSpec
    from forge_math.numeric import evaluate_matrix, build_grid
    from forge_validation import evaluate_energy_conditions

    pm, geo = geometries("alcubierre")
    subs = {pm.params[s.symbol]: v for s, v in
            zip(pm.definition.parameters.values(), (0.5, 1.0, 8.0))}
    spec = GridSpec(
        bounds={"x": (-2.0, 2.0), "y": (-2.0, 2.0)},
        resolution={"x": 24, "y": 24},
        slice_values={"t": 0.0, "z": 0.0},
    )
    _, meshes = build_grid(pm.coords, spec)
    g_arr, _ = evaluate_matrix(geo.metric.subs(subs), pm.coords, meshes, "g")
    ginv_arr, _ = evaluate_matrix(geo.inverse_metric.subs(subs), pm.coords, meshes, "g_inv")
    T_arr, _ = evaluate_matrix(geo.stress_energy.subs(subs), pm.coords, meshes, "T")

    rep = evaluate_energy_conditions(
        g_arr, ginv_arr, T_arr, ["NEC", "WEC"], sample_points=256, seed=7,
    )
    assert rep.results["WEC"].status == "confirmed_violation"
    assert rep.results["NEC"].status == "confirmed_violation"
    # Eulerian energy density: strictly negative somewhere, zero at center
    rho = rep.eulerian_energy_density
    assert np.nanmin(rho) < -1e-6
    center = rho[rho.shape[0] // 2, rho.shape[1] // 2]
    assert abs(center) < 1e-6

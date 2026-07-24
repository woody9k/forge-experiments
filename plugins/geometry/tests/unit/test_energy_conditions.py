"""Energy-condition evaluation on hand-built stress-energy fields."""

import numpy as np

from forge_validation.energy_conditions import evaluate_energy_conditions

COND = ["NEC", "WEC", "SEC", "DEC"]


def flat_arrays(shape=(4, 4, 4)):
    eta = np.diag([-1.0, 1.0, 1.0, 1.0])
    g = np.broadcast_to(eta[:, :, None, None, None], (4, 4) + shape).copy()
    return g, g.copy()


def dust_T(rho, shape=(4, 4, 4)):
    """Static dust in Minkowski: T_{μν} = ρ u_μ u_ν, u_μ = (−1,0,0,0)."""
    T = np.zeros((4, 4) + shape)
    T[0, 0] = rho
    return T


def test_positive_dust_satisfies_all_conditions():
    g, ginv = flat_arrays()
    rep = evaluate_energy_conditions(g, ginv, dust_T(+1.0), COND, sample_points=64, seed=42)
    for c in COND:
        assert rep.results[c].status == "no_violation_detected", rep.results[c]


def test_negative_dust_violates_wec_and_nec():
    g, ginv = flat_arrays()
    rep = evaluate_energy_conditions(g, ginv, dust_T(-1.0), COND, sample_points=64, seed=42)
    assert rep.results["WEC"].status == "confirmed_violation"
    assert rep.results["NEC"].status == "confirmed_violation"
    assert rep.results["WEC"].min_value < 0


def test_vacuum_is_clean_and_energy_density_zero():
    g, ginv = flat_arrays()
    T = np.zeros((4, 4, 4, 4, 4))
    rep = evaluate_energy_conditions(g, ginv, T, COND, sample_points=32, seed=1)
    assert np.allclose(rep.eulerian_energy_density, 0.0)
    for c in COND:
        assert rep.results[c].status == "no_violation_detected"


def test_nonfinite_metric_yields_inconclusive_or_failed():
    g, ginv = flat_arrays()
    g[..., 0, 0, 0] = np.nan
    ginv[..., 0, 0, 0] = np.nan
    T = dust_T(1.0)
    # tiny grid: every sampled point may be the poisoned one at low sample counts
    rep = evaluate_energy_conditions(
        g[:, :, :1, :1, :1], ginv[:, :, :1, :1, :1], T[:, :, :1, :1, :1],
        COND, sample_points=8, seed=0,
    )
    for c in COND:
        assert rep.results[c].status in ("failed", "inconclusive")

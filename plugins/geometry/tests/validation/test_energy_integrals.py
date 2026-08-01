"""Energy integrals: the arithmetic, the refusals, and one known answer.

B-16 stores three measures side by side (backlog U-4) because they disagree
and the disagreement is informative. That makes *each* of them worth pinning:
a scoring component that is quietly wrong ranks candidates wrongly, which is
the failure the whole scoring exercise exists to avoid.

The known-answer case is a flat chart where the proper and coordinate
integrals must agree exactly, and a deliberately curved one where they must
not — if those two ever give the same answer, the volume element is not being
applied at all, which is the single most likely way this module breaks.
"""

from __future__ import annotations

import numpy as np
import pytest

from forge_math.energy import (
    EnergyIntegralError,
    adm_availability,
    chart_sensitivity,
    coordinate_integral,
    energy_integrals,
    proper_integral,
    spatial_metric_determinant,
)

pytestmark = pytest.mark.validation


def _flat_grid(n=21, half=1.0):
    """A 2-D Cartesian plane with an identity spatial metric."""
    axis = np.linspace(-half, half, n)
    axes = {"x": axis, "y": axis}
    shape = (n, n)
    metric = np.zeros((4, 4, *shape))
    metric[0, 0] = -1.0
    for i in (1, 2, 3):
        metric[i, i] = 1.0
    return axes, ["t", "x", "y", "z"], metric, shape


# ------------------------------------------------------------- known answers

def test_a_uniform_density_on_a_flat_plane_integrates_to_density_times_area():
    axes, names, metric, shape = _flat_grid(n=21, half=1.0)
    rho = np.full(shape, -2.0)

    out = energy_integrals(rho, axes, names, metric=metric)

    # Midpoint-free Riemann sum over 21 samples spanning [-1, 1]: the cell
    # measure is (2/20)^2 and there are 21^2 samples, so the sampled area is
    # (21 * 0.1)^2 = 4.41 rather than 4. Assert against the sum the code
    # actually forms, not against the idealised integral — a test that
    # tolerated the difference would also tolerate a wrong volume element.
    cell = (2.0 / 20) ** 2
    expected = -2.0 * 21 * 21 * cell
    assert out["coordinate"].total == pytest.approx(expected)
    assert out["proper"].total == pytest.approx(expected)


def test_a_flat_chart_makes_the_two_measures_agree_exactly():
    """√det ³g = 1, so any disagreement means the weight is not applied."""
    axes, names, metric, shape = _flat_grid()
    rng = np.random.default_rng(11)
    rho = rng.normal(size=shape)

    out = energy_integrals(rho, axes, names, metric=metric)
    assert out["proper"].total == pytest.approx(out["coordinate"].total)
    assert chart_sensitivity(out) == pytest.approx(1.0)


def test_a_curved_chart_makes_them_differ_by_the_volume_element():
    """The regression that matters: if the volume element were dropped, this
    would silently equal the coordinate answer."""
    axes, names, metric, shape = _flat_grid(n=11)
    # Stretch y by a constant factor 4 => det = 4, sqrt(det) = 2.
    metric[2, 2] = 4.0
    rho = np.full(shape, -1.0)

    coord = coordinate_integral(rho, axes, ["x", "y"])
    proper = proper_integral(rho, metric, names, axes, ["x", "y"])

    assert proper.total == pytest.approx(2.0 * coord.total)
    assert chart_sensitivity({"coordinate": coord, "proper": proper}) \
        == pytest.approx(2.0)


def test_the_negative_part_isolates_the_exotic_region():
    axes, names, metric, shape = _flat_grid(n=11)
    rho = np.ones(shape)
    rho[:5, :] = -3.0                       # 5 of 11 rows negative

    out = energy_integrals(rho, axes, names, metric=metric)
    cell = (2.0 / 10) ** 2
    assert out["proper"].negative_part == pytest.approx(-3.0 * 5 * 11 * cell)
    assert out["proper"].negative_fraction == pytest.approx(5 / 11)
    # The total is *not* the negative part: a metric can need exotic matter
    # locally and still have positive total energy.
    assert out["proper"].total > out["proper"].negative_part


# ------------------------------------------------------------- units, honesty

def test_a_two_dimensional_slice_is_not_reported_as_an_energy():
    """Integrating a density over a plane gives energy per unit length. That
    number next to a published total would look entirely reasonable and be
    wrong by a dimension."""
    axes, names, metric, shape = _flat_grid()
    out = energy_integrals(np.full(shape, -1.0), axes, names, metric=metric)

    assert out["proper"].dimension == 2
    assert out["proper"].unit == "energy_per_unit_length"


def test_a_three_dimensional_grid_is_reported_as_an_energy():
    n = 7
    axis = np.linspace(-1, 1, n)
    axes = {"x": axis, "y": axis, "z": axis}
    shape = (n, n, n)
    metric = np.zeros((4, 4, *shape))
    metric[0, 0] = -1.0
    for i in (1, 2, 3):
        metric[i, i] = 1.0

    out = energy_integrals(np.full(shape, -1.0), axes,
                           ["t", "x", "y", "z"], metric=metric)
    assert out["proper"].dimension == 3
    assert out["proper"].unit == "energy"


def test_non_finite_density_is_refused_rather_than_masked():
    axes, names, metric, shape = _flat_grid(n=11)
    rho = np.full(shape, -1.0)
    rho[3, 4] = np.nan

    out = energy_integrals(rho, axes, names, metric=metric)
    assert out["proper"].available is False
    assert "non-finite" in out["proper"].reason
    assert out["proper"].total is None       # no sentinel, no zero


def test_a_degenerate_chart_is_refused_rather_than_abs_ed():
    """abs(det) would turn a coordinate singularity into a plausible volume
    element — the Schwarzschild-horizon class of mistake."""
    axes, names, metric, shape = _flat_grid(n=11)
    metric[2, 2] = -1.0                      # signature flip in the slice

    with pytest.raises(EnergyIntegralError, match="degenerate|signature"):
        spatial_metric_determinant(metric, names, ["x", "y"])


def test_a_non_uniform_axis_is_refused():
    axes, names, metric, shape = _flat_grid(n=11)
    axes["x"] = np.concatenate([np.linspace(-1, 0, 6),
                                np.linspace(0.5, 1, 5)])

    out = energy_integrals(np.full(shape, -1.0), axes, names, metric=metric)
    assert out["coordinate"].available is False
    assert "uniform" in out["coordinate"].reason


def test_an_empty_negative_region_says_so_rather_than_reporting_zero():
    axes, names, metric, shape = _flat_grid(n=11)
    out = energy_integrals(np.ones(shape), axes, names, metric=metric)

    assert out["proper"].negative_part == 0.0
    assert any("does not cover" in w for w in out["proper"].warnings)


# ----------------------------------------------------------------------- ADM

def test_adm_is_unavailable_on_a_plane_and_says_why():
    axes, names, metric, shape = _flat_grid()
    out = energy_integrals(np.full(shape, -1.0), axes, names, metric=metric)

    adm = out["adm"]
    assert adm.available is False
    assert adm.total is None
    assert "2-D" in adm.reason or "spatial dimension" in adm.reason


def test_adm_is_unavailable_even_in_three_dimensions_and_is_honest_about_it():
    """The gate is implemented; the surface integral is not. Reporting a
    number here would be indistinguishable from one that means something."""
    ok, reason = adm_availability(["t", "x", "y", "z"], ["x", "y", "z"],
                                  np.zeros((4, 4, 3, 3, 3)))
    assert ok is False
    assert "not implemented" in reason


def test_the_vector_always_has_all_three_entries():
    """A consumer must never be able to mistake 'missing' for 'zero'."""
    axes, names, metric, shape = _flat_grid()
    out = energy_integrals(np.full(shape, -1.0), axes, names, metric=metric)
    assert set(out) == {"coordinate", "proper", "adm"}


def test_a_missing_metric_leaves_proper_unavailable_not_silently_coordinate():
    axes, names, _metric, shape = _flat_grid()
    out = energy_integrals(np.full(shape, -1.0), axes, names, metric=None)

    assert out["coordinate"].available is True
    assert out["proper"].available is False
    assert "volume element" in out["proper"].reason

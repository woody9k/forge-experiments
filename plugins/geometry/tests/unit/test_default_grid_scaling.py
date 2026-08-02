"""A default sampling window that follows its structure.

The first sweep this platform ran held a fixed ``[-2, 2]²`` window while
varying the Alcubierre radius up to 2, so the largest bubbles had their wall
at the grid edge. Nothing failed: the integrals returned plausible numbers,
several runs reported a negative fraction of 1.00, and the fitted radius and
wall-steepness exponents moved by ~25% depending on which truncated runs
were excluded. The velocity exponent, on the one axis nothing truncates,
stayed at Alcubierre's exact 2.0 the whole time — which is what made the
contrast visible at all.

So these tests are about a *silent* failure, and the properties worth
pinning are: the scaling actually applies, it is per-axis (an angle must not
scale), the defaults are unchanged at the parameter values the goldens were
taken at, and a scale that cannot produce a sane window raises.
"""

from __future__ import annotations

import pytest

from forge_geometry.entities import DefaultGridSpec
from forge_metrics import builtin_metrics, load_metric_file
from forge_metrics.loader import MetricLoadError, _parse_default_grid


def _definition(name: str):
    return load_metric_file(builtin_metrics()[name]).definition


# ------------------------------------------------------------- the mechanism

def test_scaled_bounds_follow_their_parameter():
    spec = DefaultGridSpec(vary={"x": (-2.0, 2.0)}, scale_with={"x": "radius"})

    assert spec.resolve({"radius": 1.0}) == {"x": (-2.0, 2.0)}
    assert spec.resolve({"radius": 2.0}) == {"x": (-4.0, 4.0)}
    assert spec.resolve({"radius": 0.5}) == {"x": (-1.0, 1.0)}


def test_an_unscaled_axis_is_left_alone():
    """Per-axis on purpose: in a spherical chart the radius scales and the
    angle must not, so a blanket scaling would be wrong."""
    spec = DefaultGridSpec(vary={"r": (0.1, 3.0), "theta": (0.1, 3.04)},
                           scale_with={"r": "radius"})

    resolved = spec.resolve({"radius": 3.0})

    assert resolved["r"] == pytest.approx((0.3, 9.0))
    assert resolved["theta"] == (0.1, 3.04)   # exact: never multiplied


@pytest.mark.parametrize("scale", [0.0, -1.0])
def test_a_non_positive_scale_raises_rather_than_inverting_the_window(scale):
    spec = DefaultGridSpec(vary={"x": (-2.0, 2.0)}, scale_with={"x": "radius"})

    with pytest.raises(ValueError, match="inverts or collapses"):
        spec.resolve({"radius": scale})


def test_a_missing_scale_parameter_raises():
    spec = DefaultGridSpec(vary={"x": (-2.0, 2.0)}, scale_with={"x": "radius"})

    with pytest.raises(ValueError, match="no value"):
        spec.resolve({"velocity": 0.5})


# ------------------------------------------------------------ load-time gates

def test_scaling_an_unvaried_coordinate_is_refused_at_load():
    with pytest.raises(MetricLoadError, match="not varied"):
        _parse_default_grid(
            {"vary": {"x": [-2.0, 2.0]}, "fix": {"t": 0.0},
             "scale_with": {"t": "radius"}},
            ["t", "x"], {"radius": object()})


def test_scaling_by_an_undeclared_parameter_is_refused_at_load():
    """Caught here rather than as a KeyError from inside a sweep."""
    with pytest.raises(MetricLoadError, match="undeclared parameters"):
        _parse_default_grid(
            {"vary": {"x": [-2.0, 2.0]}, "fix": {"t": 0.0},
             "scale_with": {"x": "bubble_radius"}},
            ["t", "x"], {"radius": object()})


# ---------------------------------------------------------- bundled metrics

def test_the_warp_metrics_scale_their_radial_window_with_the_bubble():
    for name in ("alcubierre", "natario"):
        grid = _definition(name).default_grid
        assert grid.scale_with, f"{name} still has a fixed window"
        assert set(grid.scale_with.values()) == {"radius"}


def test_schwarzschild_stays_outside_the_horizon_at_every_mass():
    """A fixed [2.5, 10] straddles r = 2M as soon as M > 1.25 and samples the
    interior, where the chart is degenerate."""
    grid = _definition("schwarzschild").default_grid

    for mass in (0.5, 1.0, 2.0, 10.0):
        lo, _hi = grid.resolve({"mass": mass})["r"]
        assert lo > 2.0 * mass, f"window starts inside the horizon at M={mass}"


def test_theta_is_never_scaled_on_the_spherical_metrics():
    for name in ("natario", "schwarzschild"):
        grid = _definition(name).default_grid
        assert "theta" not in grid.scale_with
        assert grid.resolve({"radius": 5.0, "mass": 5.0})["theta"] == (0.1, 3.04)


def test_the_default_parameter_values_reproduce_the_previous_windows():
    """The goldens and every stored bundle were taken at these values, so
    the change must be a no-op there — otherwise it is not a bug fix, it is
    a silent redefinition of what the default run means."""
    expected = {
        "alcubierre": {"x": (-2.0, 2.0), "y": (-2.0, 2.0)},
        "natario": {"r": (0.1, 3.0), "theta": (0.1, 3.04)},
        "schwarzschild": {"r": (2.5, 10.0), "theta": (0.1, 3.04)},
    }
    for name, bounds in expected.items():
        definition = _definition(name)
        defaults = {k: p.default for k, p in definition.parameters.items()}
        resolved = definition.default_grid.resolve(defaults)
        assert set(resolved) == set(bounds)
        for coordinate, window in bounds.items():
            assert resolved[coordinate] == pytest.approx(window), coordinate


def test_the_scaling_change_did_not_move_any_metric_hash():
    """``default_grid`` is guidance, not physical identity, and is excluded
    from ``compute_hash``. If this ever fails, editing a sampling window has
    started orphaning every bundle produced before the edit."""
    for name in builtin_metrics():
        definition = _definition(name)
        assert definition.hash == definition.compute_hash()

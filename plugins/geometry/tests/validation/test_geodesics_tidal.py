"""Known-answer validation for the B-5 diagnostics.

Every number here is checked against a published closed form, because a
tidal magnitude or an orbit radius is exactly the kind of output that looks
plausible while being wrong — and B-5 exists to decide whether a candidate
spacetime is *survivable*, which is not a question to get quietly wrong.

References
----------
Misner, Thorne & Wheeler, *Gravitation* §31.2 (tidal tensor in the static
Schwarzschild frame); Wald, *General Relativity* §6.3 (circular orbits,
photon sphere and ISCO).
"""

from __future__ import annotations

import math

import pytest
import sympy as sp

from forge_math.diagnostics import (
    DiagnosticsError,
    circular_orbit_radii,
    evaluate_tidal,
    trace_geodesic,
)
from forge_math.pipeline import compute_geometry

pytestmark = pytest.mark.validation


def _schwarzschild(mass_value: float = 1.0):
    t, r, th, ph = sp.symbols("t r theta phi", real=True)
    M = sp.Rational(mass_value) if float(mass_value).is_integer() else sp.Float(mass_value)
    f = 1 - 2 * M / r
    g = sp.diag(-f, 1 / f, r**2, r**2 * sp.sin(th) ** 2)
    return g, [t, r, th, ph], M


def _minkowski():
    t, x, y, z = sp.symbols("t x y z", real=True)
    return sp.diag(-1, 1, 1, 1), [t, x, y, z]


# --------------------------------------------------------------- flat space

def test_minkowski_has_no_tidal_field():
    """The floor: flat spacetime stretches nothing, exactly."""
    g, coords = _minkowski()
    geo = compute_geometry(g, coords)
    report = evaluate_tidal(
        geo.riemann_up, g, coords,
        four_velocity=[1, 0, 0, 0],
        at={"t": 0.0, "x": 1.0, "y": 1.0, "z": 1.0}, vacuum=True)
    assert report.max_magnitude == pytest.approx(0.0, abs=1e-14)
    assert report.principal == pytest.approx([0.0, 0.0, 0.0, 0.0], abs=1e-14)


# ------------------------------------------------- Schwarzschild tidal field

@pytest.mark.parametrize("r_value", [10.0, 20.0, 50.0])
def test_schwarzschild_tidal_matches_the_closed_form(r_value):
    """MTW §31.2: for a static observer the tidal tensor in the orthonormal
    frame is diag(-2M/r³, +M/r³, +M/r³) — radial stretch, transverse squeeze,
    and the magnitudes must fall exactly as 1/r³."""
    mass = 1.0
    g, coords, M = _schwarzschild(mass)
    geo = compute_geometry(g, coords)

    # Static observer: u^μ = (1/sqrt(f), 0, 0, 0) so that g(u,u) = -1.
    f = 1 - 2 * mass / r_value
    u = [1 / sp.sqrt(1 - 2 * M / coords[1]), 0, 0, 0]
    at = {"r": r_value, "theta": math.pi / 2, "t": 0.0, "phi": 0.0}
    report = evaluate_tidal(geo.riemann_up, g, coords, u, at, vacuum=True)

    expected_radial = -2 * mass / r_value**3
    expected_transverse = mass / r_value**3

    assert report.trace == pytest.approx(0.0, abs=1e-12)
    # One stretch, two squeezes, and a zero along the worldline itself.
    nonzero = sorted(x for x in report.principal if abs(x) > 1e-14)
    assert nonzero[0] == pytest.approx(expected_radial, rel=1e-8)
    assert nonzero[1] == pytest.approx(expected_transverse, rel=1e-8)
    assert nonzero[2] == pytest.approx(expected_transverse, rel=1e-8)
    assert report.max_magnitude == pytest.approx(abs(expected_radial), rel=1e-8)


def test_tidal_magnitude_scales_as_inverse_r_cubed():
    """Doubling the radius must cut the tidal field by exactly 8×. This is
    the scaling a habitability claim would rest on."""
    g, coords, M = _schwarzschild(1.0)
    geo = compute_geometry(g, coords)
    u = [1 / sp.sqrt(1 - 2 * M / coords[1]), 0, 0, 0]

    def at_r(r):
        return evaluate_tidal(
            geo.riemann_up, g, coords, u,
            {"r": r, "theta": math.pi / 2, "t": 0.0, "phi": 0.0},
            vacuum=True).max_magnitude

    assert at_r(10.0) / at_r(20.0) == pytest.approx(8.0, rel=1e-8)


def test_a_singular_evaluation_point_fails_loudly():
    """At r = 2M the static frame is singular. A number here would be a lie;
    principle 2 says say so instead."""
    g, coords, M = _schwarzschild(1.0)
    geo = compute_geometry(g, coords)
    u = [1 / sp.sqrt(1 - 2 * M / coords[1]), 0, 0, 0]
    with pytest.raises(DiagnosticsError):
        evaluate_tidal(geo.riemann_up, g, coords, u,
                       {"r": 2.0, "theta": math.pi / 2, "t": 0.0, "phi": 0.0})


# ------------------------------------------------------------- geodesics

def test_a_radial_geodesic_conserves_its_norm():
    """A timelike worldline keeps g(u,u) = -1. The drift is the integration
    error, and it is reported rather than renormalised away."""
    g, coords, _ = _schwarzschild(1.0)
    geo = compute_geometry(g, coords)

    r0 = 50.0
    f = 1 - 2.0 / r0
    # Dropped from rest at r0: energy per unit mass E = sqrt(f).
    result = trace_geodesic(
        geo.christoffel, g, coords,
        x0=[0.0, r0, math.pi / 2, 0.0],
        v0=[1 / math.sqrt(f), 0.0, 0.0, 0.0],
        tau_max=20.0, steps=400)

    assert result.quality == "converged", result.warnings
    assert result.norm[0] == pytest.approx(-1.0, abs=1e-9)
    assert result.norm_drift < 1e-6
    # It falls: r decreases monotonically once released from rest.
    radii = [p[1] for p in result.position]
    assert radii[-1] < radii[0]


def test_a_circular_orbit_stays_circular():
    """At r = 12M a circular orbit is stable (well outside the ISCO), so the
    traced radius must not wander. Angular velocity from the closed form
    Ω = sqrt(M/r³)."""
    mass, r0 = 1.0, 12.0
    g, coords, _ = _schwarzschild(mass)
    geo = compute_geometry(g, coords)

    omega = math.sqrt(mass / r0**3)
    f = 1 - 2 * mass / r0
    # Normalisation: -f ṫ² + r² φ̇² = -1 with φ̇ = Ω ṫ.
    t_dot = 1.0 / math.sqrt(f - r0**2 * omega**2)
    result = trace_geodesic(
        geo.christoffel, g, coords,
        x0=[0.0, r0, math.pi / 2, 0.0],
        v0=[t_dot, 0.0, 0.0, omega * t_dot],
        tau_max=200.0, steps=2000)

    assert result.quality == "converged", result.warnings
    radii = [p[1] for p in result.position]
    assert max(abs(r - r0) for r in radii) < 1e-6 * r0


def test_landmark_radii_are_the_published_ones():
    """Photon sphere 3M, ISCO 6M, horizon 2M — Wald §6.3."""
    assert circular_orbit_radii(1.0) == {"photon_sphere": 3.0, "isco": 6.0,
                                         "horizon": 2.0}
    assert circular_orbit_radii(2.5)["isco"] == 15.0


def test_an_orbit_inside_the_isco_is_not_stable():
    """r = 5M is inside the ISCO, so a nominally circular orbit must *not*
    hold its radius — the check that the tracer reflects real dynamics
    rather than following whatever it was initialised with."""
    mass, r0 = 1.0, 5.0
    g, coords, _ = _schwarzschild(mass)
    geo = compute_geometry(g, coords)

    omega = math.sqrt(mass / r0**3)
    f = 1 - 2 * mass / r0
    t_dot = 1.0 / math.sqrt(f - r0**2 * omega**2)
    # Perturb outward by 0.1%: inside the ISCO this grows instead of oscillating.
    result = trace_geodesic(
        geo.christoffel, g, coords,
        x0=[0.0, r0 * 1.001, math.pi / 2, 0.0],
        v0=[t_dot, 0.0, 0.0, omega * t_dot],
        tau_max=400.0, steps=3000)

    radii = [p[1] for p in result.position]
    assert max(radii) - r0 > 0.05 * r0, (
        "a perturbed orbit inside the ISCO should run away, not stay put")

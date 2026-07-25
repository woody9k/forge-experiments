"""Known-answer validation of the independent backend, standing alone.

The independent path (forge_verify, orthonormal-frame route) must reproduce
the same published results the coordinate pipeline is held to — *before* it
is allowed to act as a referee for anything.  Nothing here compares the two
backends; that is test_cross_backend.py.  These tests compare the new backend
against textbook and published values.
"""

import numpy as np
import pytest
import sympy as sp

from forge_validation.suites import alcubierre_expected_energy_density
from forge_verify import check_equivalent, is_zero
from forge_verify.equivalence import Verdict

pytestmark = pytest.mark.validation

NUM_RTOL = 1e-8


def _all_zero(exprs) -> list[str]:
    """Return the components that are not provably zero."""
    bad = []
    for i, e in enumerate(exprs):
        check = is_zero(e)
        if check.verdict is not Verdict.EQUIVALENT:
            bad.append(f"[{i}] {check.verdict.value} ({check.method.value}): {e}")
    return bad


def _flat_riemann(fg):
    n = fg.dim
    return [fg.riemann_frame[a][b][c][d]
            for a in range(n) for b in range(n) for c in range(n) for d in range(n)]


def test_minkowski_is_flat(frame_geometries):
    _, fg = frame_geometries("minkowski")
    assert not _all_zero(_flat_riemann(fg))
    assert not _all_zero(list(fg.ricci_frame))
    assert not _all_zero(list(fg.einstein))
    assert not _all_zero(list(fg.stress_energy))
    assert is_zero(fg.kretschmann).verdict is Verdict.EQUIVALENT


def test_schwarzschild_vacuum_and_kretschmann(frame_geometries):
    """R_{μν} = 0 (vacuum) and K = 48M²/r⁶ (MTW), from the frame route."""
    pm, fg = frame_geometries("schwarzschild")
    assert not _all_zero(list(fg.ricci)), "Schwarzschild Ricci is not vacuum"
    assert is_zero(fg.ricci_scalar).verdict is Verdict.EQUIVALENT
    M = pm.params["M"]
    r = next(c for c in pm.coords if c.name == "r")
    check = check_equivalent(fg.kretschmann, 48 * M**2 / r**6)
    assert check.verdict is Verdict.EQUIVALENT, f"Kretschmann mismatch: {check}"
    assert check.exact
    # Curvature is genuinely present — a vacuum test alone would pass on flat space.
    assert any(is_zero(e).verdict is Verdict.DIFFERENT for e in _flat_riemann(fg))


def test_alcubierre_eulerian_energy_density_matches_published_formula(frame_geometries):
    """Alcubierre 1994 eq. 19:
        ρ = −(1/8π) v²(y²+z²)/(4r_s²) (df/dr_s)²

    In the 3+1 coframe the Eulerian observer is the timelike frame leg, so ρ
    is simply the frame component T_{00} — computed without ever forming the
    inverse metric or a coordinate Christoffel symbol.
    """
    pm, fg = frame_geometries("alcubierre")
    rho = fg.eulerian_energy_density()
    expected = alcubierre_expected_energy_density(pm)

    subs = {pm.params[s.symbol]: sp.Float(s.default)
            for s in pm.definition.parameters.values()}
    f_got = sp.lambdify(pm.coords, rho.subs(subs), modules=["numpy"])
    f_want = sp.lambdify(pm.coords, expected.subs(subs), modules=["numpy"])

    rng = np.random.default_rng(20260724)
    pts = rng.uniform(-2.0, 2.0, size=(64, 4))
    pts[:, 0] = rng.uniform(0.0, 1.0, size=64)
    got = np.array([f_got(*p) for p in pts], dtype=np.float64)
    want = np.array([f_want(*p) for p in pts], dtype=np.float64)
    finite = np.isfinite(got) & np.isfinite(want)
    assert finite.sum() >= 0.9 * len(pts)

    scale = max(np.abs(want[finite]).max(), 1e-30)
    resid = float(np.abs(got[finite] - want[finite]).max() / scale)
    assert resid < NUM_RTOL, f"max relative residual {resid:.3e} against eq. 19"
    # The published headline: the wall carries negative energy density.
    assert got[finite].min() < 0


def test_natario_zero_expansion(frame_geometries):
    """Natário 2002's headline result — θ = ∇_μ n^μ ≡ 0 — read straight off
    the rotation coefficients: for the Eulerian congruence n = E_0,
    θ = Γ^a_{a0}.

    Note this route needs no sin/cos abstraction: the frame path never
    divides by sin θ, so the polar-axis Piecewise trap (CLAUDE.md §7) does
    not arise here.
    """
    _, fg = frame_geometries("natario")
    theta = sum(fg.rotation[a][a][0] for a in range(fg.dim))
    check = is_zero(theta)
    assert check.verdict is Verdict.EQUIVALENT, f"expansion is not zero: {check}"
    assert check.exact, f"zero expansion was only established by sampling: {check}"


def test_natario_violates_the_weak_energy_condition(frame_geometries):
    """Also published: the metric still violates the WEC near the wall."""
    pm, fg = frame_geometries("natario")
    rho = fg.eulerian_energy_density()
    subs = {pm.params[s.symbol]: sp.Float(s.default)
            for s in pm.definition.parameters.values()}
    f_rho = sp.lambdify(pm.coords, rho.subs(subs), modules=["numpy"])

    rng = np.random.default_rng(20260724)
    R = pm.definition.parameters["radius"].default
    pts = np.column_stack([
        np.zeros(48),
        rng.uniform(0.5 * R, 1.5 * R, 48),
        rng.uniform(0.2, np.pi - 0.2, 48),
        rng.uniform(0.0, 2 * np.pi, 48),
    ])
    vals = np.array([f_rho(*p) for p in pts], dtype=np.float64)
    finite = vals[np.isfinite(vals)]
    assert finite.size >= 40
    assert finite.min() < 0

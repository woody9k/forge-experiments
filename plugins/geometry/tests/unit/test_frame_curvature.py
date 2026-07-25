"""The independent (orthonormal-frame) backend on small analytic geometries.

These are known-answer tests for forge_verify *standing alone* — they never
consult forge_math.pipeline, so a shared bug could not make them pass.
"""

import pytest
import sympy as sp

from forge_verify import (
    FrameGeometryError, TetradError, build_coframe, check_equivalent,
    compute_frame_geometry, is_zero,
)
from forge_verify.equivalence import Verdict


def _all_zero(exprs) -> bool:
    return all(is_zero(e).verdict is Verdict.EQUIVALENT for e in exprs)


def test_two_sphere_curvature():
    """2-sphere of radius a: R = 2/a², K = 4/a⁴ (Riemannian branch)."""
    theta, phi = sp.symbols("theta phi", real=True)
    a = sp.Symbol("a", positive=True)
    g = sp.diag(a**2, a**2 * sp.sin(theta) ** 2)
    fg = compute_frame_geometry(g, [theta, phi], signature="++",
                                simplify_level="full", compute_kretschmann=True)
    assert check_equivalent(fg.ricci_scalar, 2 / a**2).verdict is Verdict.EQUIVALENT
    assert check_equivalent(fg.kretschmann, 4 / a**4).verdict is Verdict.EQUIVALENT


def test_rindler_wedge_is_flat_with_nonzero_connection():
    """ds² = −x²dt² + dx² is flat, but its rotation coefficients are not —
    the case that catches sign errors a trivially flat metric cannot."""
    t, x = sp.symbols("t x", positive=True)
    fg = compute_frame_geometry(sp.diag(-(x**2), 1), [t, x], signature="-+",
                                simplify_level="full")
    assert any(is_zero(fg.rotation[a][b][c]).verdict is Verdict.DIFFERENT
               for a in range(2) for b in range(2) for c in range(2))
    assert _all_zero([fg.riemann_frame[a][b][c][d]
                      for a in range(2) for b in range(2)
                      for c in range(2) for d in range(2)])
    assert _all_zero(list(fg.ricci))


def test_schwarzschild_is_a_vacuum_solution_with_the_published_kretschmann():
    """R_{μν} = 0, R = 0, K = 48M²/r⁶ (MTW), Riemann ≠ 0."""
    t, r, th, ph = sp.symbols("t r theta phi", real=True)
    M = sp.Symbol("M", real=True)
    f = 1 - 2 * M / r
    g = sp.diag(-f, 1 / f, r**2, r**2 * sp.sin(th) ** 2)
    fg = compute_frame_geometry(g, [t, r, th, ph], signature="-+++",
                                simplify_level="full", compute_kretschmann=True)
    assert _all_zero(list(fg.ricci)), f"Ricci not vacuum: {fg.ricci}"
    assert is_zero(fg.ricci_scalar).verdict is Verdict.EQUIVALENT
    assert check_equivalent(fg.kretschmann, 48 * M**2 / r**6).verdict is Verdict.EQUIVALENT
    assert any(is_zero(fg.riemann_frame[a][b][c][d]).verdict is Verdict.DIFFERENT
               for a in range(4) for b in range(4) for c in range(4) for d in range(4))


def test_flat_space_in_spherical_coordinates_is_flat():
    """Curvilinear coordinates on flat space: nonzero connection, zero
    curvature — an independent check that the anholonomy bookkeeping (the
    −C^e_{cd}Γ^a_{eb} term) is right."""
    t, r, th, ph = sp.symbols("t r theta phi", real=True)
    g = sp.diag(-1, 1, r**2, r**2 * sp.sin(th) ** 2)
    fg = compute_frame_geometry(g, [t, r, th, ph], signature="-+++",
                                simplify_level="full", compute_kretschmann=True)
    assert _all_zero([fg.riemann_frame[a][b][c][d]
                      for a in range(4) for b in range(4)
                      for c in range(4) for d in range(4)])
    assert is_zero(fg.kretschmann).verdict is Verdict.EQUIVALENT


def test_coframe_reconstructs_the_metric():
    t, r = sp.symbols("t r", positive=True)
    g = sp.Matrix([[-1 + 1 / r, sp.Rational(1, 3)], [sp.Rational(1, 3), 1]])
    cf = build_coframe(g, [t, r], signature="-+")
    n = 2
    resid = sp.Matrix(n, n, lambda mu, nu: sum(
        cf.signature[a] * cf.coframe[a, mu] * cf.coframe[a, nu] for a in range(n)
    ) - g[mu, nu])
    assert _all_zero(list(resid))


def test_inverse_metric_from_the_frame_matches_the_matrix_inverse():
    """g^{μν} built as η^{ab}E_a^μE_b^ν must equal g⁻¹ — computed here by
    SymPy's own inverse purely as an oracle, not as part of the backend."""
    t, r, th = sp.symbols("t r theta", positive=True)
    g = sp.diag(-(1 - 1 / r), 1 / (1 - 1 / r), r**2)
    cf = build_coframe(g, [t, r, th], signature="-++")
    resid = cf.inverse_metric("full") - g.inv()
    assert _all_zero(list(resid))


def test_non_symmetric_metric_rejected():
    t, x = sp.symbols("t x", real=True)
    with pytest.raises(FrameGeometryError, match="not symmetric"):
        compute_frame_geometry(sp.Matrix([[-1, 1], [0, 1]]), [t, x], signature="-+")


def test_degenerate_spatial_block_rejected():
    t, x, y = sp.symbols("t x y", real=True)
    g = sp.Matrix([[-1, 0, 0], [0, 1, 1], [0, 1, 1]])
    with pytest.raises(FrameGeometryError, match="degenerate|zero"):
        compute_frame_geometry(g, [t, x, y], signature="-++")


def test_shape_mismatch_rejected():
    t, x, y = sp.symbols("t x y", real=True)
    with pytest.raises(FrameGeometryError, match="shape"):
        compute_frame_geometry(sp.eye(2), [t, x, y], signature="-++")


def test_unsupported_signature_rejected():
    """No silent fallback for signatures the tetrad builder cannot handle."""
    w, x, y, z = sp.symbols("w x y z", real=True)
    with pytest.raises((FrameGeometryError, TetradError), match="signature"):
        compute_frame_geometry(sp.diag(-1, -1, 1, 1), [w, x, y, z], signature="--++")

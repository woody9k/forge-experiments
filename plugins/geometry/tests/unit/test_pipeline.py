"""Tensor pipeline unit tests on small analytically known geometries."""

import pytest
import sympy as sp

from forge_math.pipeline import GeometryPipelineError, compute_geometry


def test_two_sphere_curvature():
    """2-sphere of radius a: Ricci scalar R = 2/a², Kretschmann K = 4/a⁴."""
    theta, phi = sp.symbols("theta phi", real=True)
    a = sp.Symbol("a", positive=True)
    g = sp.diag(a**2, a**2 * sp.sin(theta) ** 2)
    geo = compute_geometry(g, [theta, phi])
    assert sp.simplify(geo.ricci_scalar - 2 / a**2) == 0
    assert sp.simplify(geo.kretschmann - 4 / a**4) == 0


def test_rindler_wedge_is_flat():
    """Rindler coordinates: ds² = −x²dt² + dx² is flat (Riemann ≡ 0) even
    though Christoffel symbols are nonzero — catches sign errors that a
    trivially flat metric cannot."""
    t, x = sp.symbols("t x", real=True)
    g = sp.diag(-(x**2), 1)
    geo = compute_geometry(g, [t, x])
    assert any(sp.simplify(c) != 0
               for row in geo.christoffel for col in row for c in col)
    n = 2
    assert all(
        sp.simplify(geo.riemann_up[a][b][c][d]) == 0
        for a in range(n) for b in range(n) for c in range(n) for d in range(n)
    )


def test_nonsymmetric_metric_rejected():
    t, x = sp.symbols("t x", real=True)
    g = sp.Matrix([[-1, 1], [0, 1]])
    with pytest.raises(GeometryPipelineError, match="not symmetric"):
        compute_geometry(g, [t, x])


def test_degenerate_metric_rejected():
    t, x = sp.symbols("t x", real=True)
    g = sp.Matrix([[1, 1], [1, 1]])
    with pytest.raises(GeometryPipelineError, match="determinant"):
        compute_geometry(g, [t, x])


def test_shape_mismatch_rejected():
    t, x, y = sp.symbols("t x y", real=True)
    with pytest.raises(GeometryPipelineError, match="shape"):
        compute_geometry(sp.eye(2), [t, x, y])


def test_stress_energy_is_einstein_over_8pi():
    theta, phi = sp.symbols("theta phi", real=True)
    g = sp.diag(1, sp.sin(theta) ** 2)
    geo = compute_geometry(g, [theta, phi])
    for i in range(2):
        for j in range(2):
            assert sp.simplify(geo.stress_energy[i, j] - geo.einstein[i, j] / (8 * sp.pi)) == 0

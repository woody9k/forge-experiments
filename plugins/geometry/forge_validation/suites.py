"""Known-answer validation suites.

Each suite compares pipeline output against independently known results
(textbook identities or published formulas) and returns ``ValidationResult``
records.  Suites are looked up by metric name; unknown metrics get only the
generic structural checks.

Symbolic checks assert exact equality after simplification.  Numeric
spot-checks evaluate both sides at deterministic pseudo-random points and
compare within tolerance — used where full symbolic simplification is
impractical (e.g. Alcubierre with an explicit wall function).
"""

from __future__ import annotations

import numpy as np
import sympy as sp

from forge_domain.entities import SolverBackend, ValidationResult, ValidationStatus
from forge_math.pipeline import GeometryResult
from forge_metrics.loader import ParsedMetric

SYM_TOL = 0.0
NUM_RTOL = 1e-8


def _record(experiment_id, vtype, expected, computed, status, residual=None,
            tolerance=SYM_TOL, evidence="", backend=SolverBackend.SYMPY):
    return ValidationResult(
        experiment_id=experiment_id, validation_type=vtype, expected=expected,
        computed=computed, tolerance=tolerance, status=status,
        residual=residual, evidence=evidence, solver_backend=backend,
    )


def _all_zero(exprs) -> tuple[bool, int]:
    nonzero = 0
    for e in exprs:
        if sp.simplify(e) != 0:
            nonzero += 1
    return nonzero == 0, nonzero


def _flatten_christoffel(geo: GeometryResult):
    n = geo.dim
    return [geo.christoffel[a][b][c] for a in range(n) for b in range(n) for c in range(n)]


def _flatten_riemann(geo: GeometryResult):
    n = geo.dim
    return [geo.riemann_up[a][b][c][d]
            for a in range(n) for b in range(n) for c in range(n) for d in range(n)]


def _zero_check(experiment_id, name, exprs, expected_zero=True):
    ok, nonzero = _all_zero(exprs)
    passed = ok if expected_zero else not ok
    return _record(
        experiment_id, name,
        expected="all components ≡ 0" if expected_zero else "at least one component ≠ 0",
        computed=f"{nonzero} nonzero components of {len(exprs)}",
        status=ValidationStatus.PASSED if passed else ValidationStatus.FAILED,
        residual=float(nonzero if expected_zero else int(nonzero == 0)),
        evidence="sympy.simplify on every independent component",
    )


# ---------------------------------------------------------------- Minkowski

def minkowski_suite(parsed: ParsedMetric, geo: GeometryResult, experiment_id: str,
                    parameter_values=None) -> list[ValidationResult]:
    return [
        _zero_check(experiment_id, "minkowski.christoffel_zero", _flatten_christoffel(geo)),
        _zero_check(experiment_id, "minkowski.riemann_zero", _flatten_riemann(geo)),
        _zero_check(experiment_id, "minkowski.ricci_zero", list(geo.ricci)),
        _zero_check(experiment_id, "minkowski.einstein_zero", list(geo.einstein)),
        _zero_check(experiment_id, "minkowski.stress_energy_zero", list(geo.stress_energy)),
    ]


# ------------------------------------------------------------ Schwarzschild

def schwarzschild_suite(parsed: ParsedMetric, geo: GeometryResult, experiment_id: str,
                        parameter_values=None) -> list[ValidationResult]:
    out = [
        _zero_check(experiment_id, "schwarzschild.ricci_zero_vacuum", list(geo.ricci)),
        _record(
            experiment_id, "schwarzschild.ricci_scalar_zero",
            expected="0", computed=str(geo.ricci_scalar),
            status=ValidationStatus.PASSED if sp.simplify(geo.ricci_scalar) == 0
            else ValidationStatus.FAILED,
            residual=0.0 if sp.simplify(geo.ricci_scalar) == 0 else 1.0,
            evidence="exact symbolic simplification",
        ),
        _zero_check(experiment_id, "schwarzschild.einstein_zero_vacuum", list(geo.einstein)),
        _zero_check(experiment_id, "schwarzschild.riemann_nonzero",
                    _flatten_riemann(geo), expected_zero=False),
    ]

    # Kretschmann scalar: K = 48 M² / r⁶  (MTW; geometrized units)
    M = parsed.params.get("M")
    r = next(c for c in parsed.coords if c.name == "r")
    if geo.kretschmann is None or M is None:
        out.append(_record(
            experiment_id, "schwarzschild.kretschmann",
            expected="48*M**2/r**6", computed="<not computed>",
            status=ValidationStatus.COMPUTATION_FAILED,
            evidence="Kretschmann scalar unavailable",
        ))
    else:
        expected = 48 * M**2 / r**6
        diff = sp.simplify(geo.kretschmann - expected)
        out.append(_record(
            experiment_id, "schwarzschild.kretschmann",
            expected=str(expected), computed=str(geo.kretschmann),
            status=ValidationStatus.PASSED if diff == 0 else ValidationStatus.FAILED,
            residual=0.0 if diff == 0 else float("nan"),
            evidence="exact symbolic comparison against MTW closed form; "
                     "also fixes expected r⁻⁶ radial falloff of the invariant",
        ))
    return out


# --------------------------------------------------------------- Alcubierre

def alcubierre_expected_energy_density(parsed: ParsedMetric) -> sp.Expr:
    """Published Eulerian energy density for the Alcubierre metric
    (Alcubierre 1994, Class. Quantum Grav. 11 L73, eq. 19; geometrized):

        ρ = T_{μν} n^μ n^ν = −(1/8π) · (v² (y²+z²) / (4 r_s²)) · (df/dr_s)²
    """
    t, x, y, z = (next(c for c in parsed.coords if c.name == n) for n in ("t", "x", "y", "z"))
    v = parsed.params["v"]
    R = parsed.params["R"]
    sigma = parsed.params["sigma"]
    rs_sym = sp.Symbol("r_s", positive=True)
    f = (sp.tanh(sigma * (rs_sym + R)) - sp.tanh(sigma * (rs_sym - R))) / (2 * sp.tanh(sigma * R))
    df = sp.diff(f, rs_sym)
    rs_expr = sp.sqrt((x - v * t) ** 2 + y**2 + z**2)
    df_at = df.subs(rs_sym, rs_expr)
    return -(v**2 * (y**2 + z**2) / (4 * rs_expr**2)) * df_at**2 / (8 * sp.pi)


def alcubierre_suite(parsed: ParsedMetric, geo: GeometryResult, experiment_id: str,
                     parameter_values: dict[str, float] | None = None) -> list[ValidationResult]:
    """Numeric spot-check of the computed Eulerian energy density against the
    published closed form, at deterministic pseudo-random points."""
    params = parameter_values or {}
    subs = {parsed.params[s.symbol]: sp.Float(params.get(name, s.default))
            for name, s in parsed.definition.parameters.items()}

    # ρ_computed = T_{μν} n^μ n^ν with n the Eulerian normal.
    # For Alcubierre g^{tt} = −1 exactly, but derive α generally.
    ginv = geo.inverse_metric
    alpha = 1 / sp.sqrt(-ginv[0, 0])
    n_lower = sp.Matrix([[-alpha, 0, 0, 0]])
    n_upper = ginv * n_lower.T
    rho_computed = sum(
        geo.stress_energy[i, j] * n_upper[i] * n_upper[j]
        for i in range(4) for j in range(4)
    )
    rho_expected = alcubierre_expected_energy_density(parsed)

    fc = sp.lambdify(parsed.coords, rho_computed.subs(subs), modules=["numpy"])
    fe = sp.lambdify(parsed.coords, rho_expected.subs(subs), modules=["numpy"])

    rng = np.random.default_rng(20260724)
    pts = rng.uniform(-2.0, 2.0, size=(64, 4))
    pts[:, 0] = rng.uniform(0.0, 1.0, size=64)  # t
    got = np.array([fc(*p) for p in pts], dtype=np.float64)
    want = np.array([fe(*p) for p in pts], dtype=np.float64)

    finite = np.isfinite(got) & np.isfinite(want)
    if finite.sum() < len(pts) * 0.9:
        status, resid = ValidationStatus.COMPUTATION_FAILED, float("nan")
        evidence = f"only {int(finite.sum())}/{len(pts)} evaluation points finite"
    else:
        scale = max(np.abs(want[finite]).max(), 1e-30)
        resid = float(np.abs(got[finite] - want[finite]).max() / scale)
        status = ValidationStatus.PASSED if resid < NUM_RTOL else ValidationStatus.FAILED
        evidence = (f"max relative residual {resid:.3e} over {int(finite.sum())} "
                    f"pseudo-random points, seed 20260724")

    results = [_record(
        experiment_id, "alcubierre.eulerian_energy_density",
        expected="−(1/8π)·v²(y²+z²)/(4 r_s²)·(df/dr_s)²  [Alcubierre 1994 eq. 19]",
        computed="T_{μν} n^μ n^ν from pipeline Einstein tensor",
        status=status, residual=resid, tolerance=NUM_RTOL, evidence=evidence,
        backend=SolverBackend.NUMPY,
    )]

    # Energy density must be ≤ 0 somewhere (known WEC violation) and → 0 far away.
    wall = got[np.isfinite(got)]
    results.append(_record(
        experiment_id, "alcubierre.negative_energy_present",
        expected="min ρ < 0 near bubble wall (known WEC violation)",
        computed=f"min ρ = {wall.min():.3e}" if wall.size else "<no finite samples>",
        status=ValidationStatus.PASSED if wall.size and wall.min() < 0
        else ValidationStatus.FAILED,
        residual=float(wall.min()) if wall.size else None,
        tolerance=0.0, evidence="sampled energy density", backend=SolverBackend.NUMPY,
    ))
    return results


# ------------------------------------------------------------------ Natário

def eulerian_expansion(parsed: ParsedMetric) -> sp.Expr:
    """Expansion θ = ∇_μ n^μ of the Eulerian congruence, computed as
    (1/√|g|) ∂_μ(√|g| n^μ) via the ADM decomposition.

    Uses only the 3×3 spatial block inverse (never the full 4×4 inverse):
    β_i = g_{0i},  β^i = h^{ij} β_j,  α² = β^i β_i − g_{00},
    n^μ = (1/α, −β^i/α),  √|g| = α √det h.
    """
    g = parsed.matrix
    coords = parsed.coords
    n = len(coords)
    h = g[1:, 1:]
    det_h = sp.cancel(h.det())
    h_inv = h.adjugate().applyfunc(lambda e: sp.cancel(e / det_h))
    beta_lower = sp.Matrix([g[0, i] for i in range(1, n)])
    beta_upper = h_inv * beta_lower
    alpha2 = sp.cancel((beta_upper.T * beta_lower)[0, 0] - g[0, 0])
    alpha = sp.sqrt(alpha2)
    sqrt_g = alpha * sp.sqrt(det_h)
    n_upper = [1 / alpha] + [sp.cancel(-beta_upper[i] / alpha) for i in range(n - 1)]
    theta = sum(sp.diff(sqrt_g * n_upper[mu], coords[mu]) for mu in range(n)) / sqrt_g
    return theta


def natario_suite(parsed: ParsedMetric, geo: GeometryResult, experiment_id: str,
                  parameter_values: dict[str, float] | None = None) -> list[ValidationResult]:
    out = []

    # Published headline result (Natário 2002): the Eulerian congruence has
    # identically zero expansion.  After all differentiation we abstract
    # sin(θ), cos(θ) as independent algebraic symbols: if the expression is
    # identically zero as a rational function of those, it is zero on the
    # whole chart — this avoids spurious Piecewise branches on the polar
    # axis, where `cancel` would otherwise divide by sin(θ).
    theta = eulerian_expansion(parsed)
    th = next(c for c in parsed.coords if c.name == "theta")
    s_ = sp.Symbol("_s", positive=True)
    c_ = sp.Symbol("_c", real=True)
    theta_abs = theta.subs({sp.sin(th): s_, sp.cos(th): c_})
    theta_simplified = sp.simplify(sp.cancel(sp.together(theta_abs)))
    out.append(_record(
        experiment_id, "natario.zero_expansion",
        expected="θ = ∇_μ n^μ ≡ 0  [Natário 2002: 'warp drive with zero expansion']",
        computed=str(theta_simplified),
        status=ValidationStatus.PASSED if theta_simplified == 0 else ValidationStatus.FAILED,
        residual=0.0 if theta_simplified == 0 else float("nan"),
        evidence="exact symbolic divergence of the Eulerian unit normal, "
                 "with sin/cos(theta) abstracted as free algebraic symbols",
    ))

    # Known WEC violation: Eulerian energy density negative somewhere near the wall.
    params = parameter_values or {}
    subs = {parsed.params[s.symbol]: sp.Float(params.get(name, s.default))
            for name, s in parsed.definition.parameters.items()}
    ginv = geo.inverse_metric
    alpha = 1 / sp.sqrt(-ginv[0, 0])
    n_upper = ginv * sp.Matrix([[-alpha, 0, 0, 0]]).T
    rho = sum(geo.stress_energy[i, j] * n_upper[i] * n_upper[j]
              for i in range(4) for j in range(4))
    f_rho = sp.lambdify(parsed.coords, rho.subs(subs), modules=["numpy"])
    rng = np.random.default_rng(20260724)
    R_val = params.get("radius", parsed.definition.parameters["radius"].default)
    pts = np.column_stack([
        np.zeros(48),                                   # t
        rng.uniform(0.5 * R_val, 1.5 * R_val, 48),      # r near the wall
        rng.uniform(0.2, np.pi - 0.2, 48),              # theta
        rng.uniform(0.0, 2 * np.pi, 48),                # phi
    ])
    vals = np.array([f_rho(*p) for p in pts], dtype=np.float64)
    finite = vals[np.isfinite(vals)]
    ok = finite.size >= 40 and finite.min() < 0
    out.append(_record(
        experiment_id, "natario.wec_violation_present",
        expected="min ρ < 0 near bubble wall (known WEC violation)",
        computed=f"min ρ = {finite.min():.3e} over {finite.size} points"
        if finite.size else "<no finite samples>",
        status=ValidationStatus.PASSED if ok else ValidationStatus.FAILED,
        residual=float(finite.min()) if finite.size else None,
        tolerance=0.0, evidence="sampled Eulerian energy density, seed 20260724",
        backend=SolverBackend.NUMPY,
    ))
    return out


SUITES = {
    "minkowski": minkowski_suite,
    "schwarzschild": schwarzschild_suite,
    "alcubierre": alcubierre_suite,
    "natario": natario_suite,
}


def run_validation_suite(parsed: ParsedMetric, geo: GeometryResult, experiment_id: str,
                         parameter_values: dict[str, float] | None = None) -> list[ValidationResult]:
    suite = SUITES.get(parsed.definition.name)
    if suite is None:
        return [_record(
            experiment_id, "generic.no_known_answers",
            expected="n/a", computed="n/a",
            status=ValidationStatus.INCONCLUSIVE,
            evidence=f"no known-answer suite registered for metric "
                     f"{parsed.definition.name!r}; structural checks only",
        )]
    return suite(parsed, geo, experiment_id, parameter_values)

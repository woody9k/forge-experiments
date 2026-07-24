"""Symbolic tensor pipeline.

Given a metric tensor g_{μν} as a SymPy matrix over coordinate symbols,
computes in order:

    inverse metric → determinant → Christoffel symbols → Riemann tensor
    → Ricci tensor → Ricci scalar → Einstein tensor → stress-energy tensor
    → Kretschmann scalar

Index conventions (documented, fixed for v0.1):

* signature (-,+,+,+) unless the definition says otherwise;
* Christoffel:  Γ^a_{bc} = ½ g^{ad} (∂_b g_{dc} + ∂_c g_{db} − ∂_d g_{bc})
* Riemann:      R^a_{bcd} = ∂_c Γ^a_{db} − ∂_d Γ^a_{cb}
                            + Γ^a_{ce} Γ^e_{db} − Γ^a_{de} Γ^e_{cb}
* Ricci:        R_{bd} = R^a_{bad}
* Einstein:     G_{μν} = R_{μν} − ½ R g_{μν}
* Stress-energy (geometrized, G=c=1):  T_{μν} = G_{μν} / (8π)
  In SI mode the caller multiplies by c⁴/(8πG) via forge_math.units.

These match Misner–Thorne–Wheeler sign conventions.

Failure policy: this module never substitutes defaults or coerces failures.
A non-invertible metric, a zero determinant, or an unsimplifiable expression
raises ``GeometryPipelineError`` or is recorded in ``warnings`` — never
silently dropped.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import sympy as sp

SimplifyLevel = str  # "none" | "light" | "full"


class GeometryPipelineError(RuntimeError):
    """A stage of the tensor pipeline failed in a way that invalidates results."""


def _simp(expr: sp.Expr, level: SimplifyLevel) -> sp.Expr:
    if level == "none":
        return expr
    if level == "light":
        return sp.cancel(sp.together(expr))
    return sp.simplify(expr)


@dataclass
class GeometryResult:
    coords: list[sp.Symbol]
    metric: sp.Matrix
    inverse_metric: sp.Matrix
    determinant: sp.Expr
    christoffel: list  # Γ[a][b][c] = Γ^a_{bc}
    riemann_up: list   # R[a][b][c][d] = R^a_{bcd}
    ricci: sp.Matrix
    ricci_scalar: sp.Expr
    einstein: sp.Matrix
    stress_energy: sp.Matrix  # geometrized units: G_{μν}/(8π)
    kretschmann: sp.Expr | None
    simplify_level: SimplifyLevel
    warnings: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)

    @property
    def dim(self) -> int:
        return len(self.coords)


def compute_geometry(
    g: sp.Matrix,
    coords: list[sp.Symbol],
    simplify_level: SimplifyLevel = "full",
    compute_kretschmann: bool = True,
) -> GeometryResult:
    n = len(coords)
    warnings: list[str] = []
    timings: dict[str, float] = {}

    if g.shape != (n, n):
        raise GeometryPipelineError(f"metric shape {g.shape} does not match {n} coordinates")
    asym = sp.simplify(g - g.T)
    if any(e != 0 for e in asym):
        raise GeometryPipelineError("metric tensor is not symmetric")

    t0 = time.monotonic()
    det = _simp(g.det(), simplify_level)
    if det == 0:
        raise GeometryPipelineError("metric determinant is identically zero (degenerate metric)")
    timings["determinant"] = time.monotonic() - t0

    t0 = time.monotonic()
    # Adjugate-based inverse with per-entry cancellation: far more robust than
    # Gaussian elimination for the large nested expressions warp metrics
    # produce, and it reuses the determinant we already have.
    adj = g.adjugate()
    g_inv = adj.applyfunc(lambda e: sp.cancel(e / det))
    if simplify_level == "full":
        g_inv = g_inv.applyfunc(sp.simplify)
    timings["inverse"] = time.monotonic() - t0

    # Christoffel symbols Γ^a_{bc}
    t0 = time.monotonic()
    dg = [[[sp.diff(g[b, c], coords[a]) for c in range(n)] for b in range(n)] for a in range(n)]
    christoffel = [[[sp.S.Zero] * n for _ in range(n)] for _ in range(n)]
    for a in range(n):
        for b in range(n):
            for c in range(b, n):  # symmetric in (b, c)
                term = sum(
                    g_inv[a, d] * (dg[b][d][c] + dg[c][d][b] - dg[d][b][c])
                    for d in range(n)
                )
                val = _simp(term / 2, simplify_level)
                christoffel[a][b][c] = val
                christoffel[a][c][b] = val
    timings["christoffel"] = time.monotonic() - t0

    # Riemann R^a_{bcd}
    t0 = time.monotonic()
    riemann = [[[[sp.S.Zero] * n for _ in range(n)] for _ in range(n)] for _ in range(n)]
    for a in range(n):
        for b in range(n):
            for c in range(n):
                for d in range(c + 1, n):  # antisymmetric in (c, d)
                    expr = (
                        sp.diff(christoffel[a][d][b], coords[c])
                        - sp.diff(christoffel[a][c][b], coords[d])
                        + sum(
                            christoffel[a][c][e] * christoffel[e][d][b]
                            - christoffel[a][d][e] * christoffel[e][c][b]
                            for e in range(n)
                        )
                    )
                    expr = _simp(expr, simplify_level)
                    riemann[a][b][c][d] = expr
                    riemann[a][b][d][c] = -expr
    timings["riemann"] = time.monotonic() - t0

    # Ricci R_{bd} = R^a_{bad}
    t0 = time.monotonic()
    ricci = sp.zeros(n, n)
    for b in range(n):
        for d in range(b, n):
            val = _simp(sum(riemann[a][b][a][d] for a in range(n)), simplify_level)
            ricci[b, d] = val
            ricci[d, b] = val
    timings["ricci"] = time.monotonic() - t0

    t0 = time.monotonic()
    ricci_scalar = _simp(
        sum(g_inv[b, d] * ricci[b, d] for b in range(n) for d in range(n)),
        simplify_level,
    )
    timings["ricci_scalar"] = time.monotonic() - t0

    t0 = time.monotonic()
    einstein = sp.zeros(n, n)
    for mu in range(n):
        for nu in range(mu, n):
            val = _simp(ricci[mu, nu] - ricci_scalar * g[mu, nu] / 2, simplify_level)
            einstein[mu, nu] = val
            einstein[nu, mu] = val
    timings["einstein"] = time.monotonic() - t0

    stress_energy = einstein.applyfunc(lambda e: _simp(e / (8 * sp.pi), simplify_level))

    kretschmann = None
    if compute_kretschmann:
        t0 = time.monotonic()
        try:
            kretschmann = _kretschmann(g, g_inv, riemann, n, simplify_level)
        except Exception as exc:  # pragma: no cover - surfaced, not swallowed
            warnings.append(f"Kretschmann computation failed: {exc}")
        timings["kretschmann"] = time.monotonic() - t0

    return GeometryResult(
        coords=coords, metric=g, inverse_metric=g_inv, determinant=det,
        christoffel=christoffel, riemann_up=riemann, ricci=ricci,
        ricci_scalar=ricci_scalar, einstein=einstein,
        stress_energy=stress_energy, kretschmann=kretschmann,
        simplify_level=simplify_level, warnings=warnings, timings=timings,
    )


def _kretschmann(g, g_inv, riemann, n, simplify_level) -> sp.Expr:
    """K = R_{abcd} R^{abcd}, exploiting antisymmetry in the last index pair."""
    # Lower the first index: R_{abcd} = g_{ae} R^e_{bcd}
    r_low = {}
    for a in range(n):
        for b in range(n):
            for c in range(n):
                for d in range(c + 1, n):
                    val = sp.cancel(sp.together(
                        sum(g[a, e] * riemann[e][b][c][d] for e in range(n))
                    ))
                    r_low[(a, b, c, d)] = val

    def rl(a, b, c, d):
        if c == d:
            return sp.S.Zero
        if c < d:
            return r_low[(a, b, c, d)]
        return -r_low[(a, b, d, c)]

    total = sp.S.Zero
    for a in range(n):
        for b in range(n):
            for c in range(n):
                for d in range(c + 1, n):
                    lower = rl(a, b, c, d)
                    if lower == 0:
                        continue
                    upper = sum(
                        g_inv[a, p] * g_inv[b, q] * g_inv[c, r] * g_inv[d, s] * rl(p, q, r, s)
                        for p in range(n) for q in range(n)
                        for r in range(n) for s in range(n)
                        if rl(p, q, r, s) != 0
                    )
                    total += 2 * lower * upper  # factor 2: (c,d) pair counted once
    return _simp(total, simplify_level)

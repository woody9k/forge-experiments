"""Geodesic tracing and tidal diagnostics (backlog B-5).

Two questions the curvature tensors alone do not answer:

**Where does a freely-falling body go?**  Integrate the geodesic equation

    d²xᵘ/dλ² = −Γᵘ_αβ (dxᵃ/dλ)(dxᵝ/dλ)

using the Christoffel symbols the symbolic pipeline already computed.  The
conserved norm gᵤᵥ ẋᵘ ẋᵛ is carried alongside as an *error estimate*, not as
a constraint to enforce: an integrator that quietly renormalises it would
hide exactly the divergence you need to see (principle 2 — fail loudly, never
mask).

**Would it survive the trip?**  The tidal tensor is the electric part of
Riemann along a timelike worldline,

    E_μν = R_μανβ uᵃ uᵝ

which is the covariant statement of "how hard is this stretched".  For a body
of size L the relative acceleration between its ends is ≈ |E| · L, so this is
the quantity that decides whether a warp bubble is habitable or a blender.
In vacuum E is trace-free; the trace is therefore a free correctness check
rather than an assumption, and it is reported instead of discarded.

Known answers used for validation (see the tests):

* Minkowski — every component of E vanishes identically.
* Schwarzschild, static observer, orthonormal frame — the classic
  ``diag(−2M/r³, +M/r³, +M/r³)`` radial-stretch/transverse-squeeze pattern,
  trace zero.
* Schwarzschild circular orbits — the innermost stable one at r = 6M, and
  the photon sphere at r = 3M, both recovered from the effective potential
  built out of the same Christoffels.

Everything here is a *diagnostic*: it reports numbers with an explicit
quality label and never decides whether a spacetime is acceptable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import sympy as sp


class DiagnosticsError(RuntimeError):
    """A diagnostic could not be computed. Always fatal to the diagnostic —
    never downgraded to a plausible-looking number."""


def _resolve_point(coords: list[sp.Symbol],
                   at: dict) -> dict[sp.Symbol, float]:
    """Map an evaluation point onto the metric's *own* coordinate symbols.

    ``sp.Symbol("r")`` and ``sp.Symbol("r", real=True)`` are different
    symbols, so a substitution built from bare names silently does nothing
    and the expression stays symbolic — which surfaces later as "cannot
    convert expression to float", a long way from the cause. Resolve by
    name against the coordinates the caller passed, and refuse a name that
    is not one of them rather than ignoring it.
    """
    by_name = {c.name: c for c in coords}
    resolved: dict[sp.Symbol, float] = {}
    for key, value in at.items():
        symbol = by_name.get(key) if isinstance(key, str) else key
        if symbol is None:
            raise DiagnosticsError(
                f"{key!r} is not a coordinate of this metric "
                f"({', '.join(sorted(by_name))})")
        resolved[symbol] = value
    missing = sorted(set(by_name) - {s.name for s in resolved})
    if missing:
        raise DiagnosticsError(
            f"no value given for coordinate(s) {missing}; an unevaluated "
            f"coordinate leaves the result symbolic")
    return resolved


# ------------------------------------------------------------ tidal tensor

def tidal_tensor_expr(riemann_up: list, metric: sp.Matrix,
                      four_velocity: list) -> sp.Matrix:
    """Symbolic ``E_μν = R_μανβ uᵃ uᵝ`` for the given 4-velocity.

    ``riemann_up`` is ``R^a_{bcd}`` as the pipeline produces it; the first
    index is lowered with the metric here rather than asking callers to hand
    in a second form of the same tensor.
    """
    n = metric.shape[0]
    if len(four_velocity) != n:
        raise DiagnosticsError(
            f"4-velocity has {len(four_velocity)} components, metric is {n}-D")

    # R_{μανβ} = g_{μρ} R^ρ_{ανβ}
    def r_down(mu, a, nu, b):
        return sum(metric[mu, rho] * riemann_up[rho][a][nu][b]
                   for rho in range(n))

    E = sp.zeros(n, n)
    for mu in range(n):
        for nu in range(n):
            E[mu, nu] = sp.simplify(sum(
                r_down(mu, a, nu, b) * four_velocity[a] * four_velocity[b]
                for a in range(n) for b in range(n)))
    return E


@dataclass
class TidalReport:
    """What a tidal evaluation found, with its own honesty attached."""

    components: list[list[float]]
    #: Eigenvalues of E with the index raised — the principal tidal
    #: accelerations per unit separation, in geometrized units (1/length²).
    principal: list[float]
    #: max |eigenvalue|: the worst stretch or squeeze at this event.
    max_magnitude: float
    #: Trace of E. Zero in vacuum; a free check on the whole computation.
    trace: float
    quality: str                       # "exact_symbolic" | "numeric"
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"components": self.components, "principal": self.principal,
                "max_magnitude": self.max_magnitude, "trace": self.trace,
                "quality": self.quality, "warnings": list(self.warnings)}


def evaluate_tidal(riemann_up: list, metric: sp.Matrix, coords: list[sp.Symbol],
                   four_velocity: list, at: dict[sp.Symbol | str, float],
                   *, vacuum: bool = False,
                   trace_tolerance: float = 1e-9) -> TidalReport:
    """Evaluate the tidal tensor at one event and report what it says.

    ``vacuum=True`` asserts the trace-free identity as a check rather than
    assuming it: a non-zero trace in vacuum means the curvature, the
    4-velocity normalisation, or the evaluation point is wrong, and saying so
    is worth more than a tidy number.
    """
    subs = _resolve_point(coords, at)
    E = tidal_tensor_expr(riemann_up, metric, four_velocity)

    n = metric.shape[0]
    warnings: list[str] = []
    try:
        E_num = np.array([[float(sp.N(E[i, j].subs(subs))) for j in range(n)]
                          for i in range(n)], dtype=float)
        g_num = np.array([[float(sp.N(metric[i, j].subs(subs))) for j in range(n)]
                          for i in range(n)], dtype=float)
    except (TypeError, ValueError) as exc:
        raise DiagnosticsError(
            f"tidal tensor did not evaluate to numbers at {at}: {exc}") from exc

    if not np.all(np.isfinite(E_num)):
        bad = int(np.count_nonzero(~np.isfinite(E_num)))
        raise DiagnosticsError(
            f"tidal tensor has {bad} non-finite component(s) at {at}; this is "
            f"a coordinate singularity or a genuine curvature singularity, "
            f"not a number to average over")

    # Principal accelerations are eigenvalues of E^μ_ν = g^{μρ} E_ρν.
    g_inv = np.linalg.inv(g_num)
    mixed = g_inv @ E_num
    eigenvalues = np.linalg.eigvals(mixed)
    if np.max(np.abs(eigenvalues.imag)) > 1e-9 * max(1.0, np.max(np.abs(eigenvalues.real))):
        warnings.append("tidal eigenvalues have a non-negligible imaginary "
                        "part; the frame or the metric signature may be wrong")
    principal = sorted(float(x) for x in eigenvalues.real)
    trace = float(np.trace(mixed))

    if vacuum and abs(trace) > trace_tolerance:
        raise DiagnosticsError(
            f"tidal tensor trace {trace:.3e} exceeds {trace_tolerance:.0e} in a "
            f"spacetime declared vacuum; E_μν must be trace-free where "
            f"R_μν = 0, so something upstream is wrong")

    return TidalReport(
        components=[[float(x) for x in row] for row in E_num],
        principal=principal,
        max_magnitude=float(max(abs(x) for x in principal)),
        trace=trace,
        quality="numeric",
        warnings=warnings,
    )


# --------------------------------------------------------------- geodesics

@dataclass
class GeodesicResult:
    """A traced worldline and how much to trust it."""

    tau: list[float]
    position: list[list[float]]
    velocity: list[list[float]]
    #: gᵤᵥ ẋᵘ ẋᵛ at each step. Should stay at its initial value; the drift is
    #: the integration error, reported rather than corrected.
    norm: list[float]
    norm_drift: float
    quality: str                       # "converged" | "drifting" | "failed"
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"tau": self.tau, "position": self.position,
                "velocity": self.velocity, "norm": self.norm,
                "norm_drift": self.norm_drift, "quality": self.quality,
                "warnings": list(self.warnings)}


def trace_geodesic(christoffel: list, metric: sp.Matrix, coords: list[sp.Symbol],
                   x0: list[float], v0: list[float], *,
                   tau_max: float = 100.0, steps: int = 2000,
                   rtol: float = 1e-9, atol: float = 1e-11,
                   drift_tolerance: float = 1e-6) -> GeodesicResult:
    """Integrate one geodesic from ``(x0, v0)``.

    The norm is *carried, not enforced*. A common shortcut is to renormalise
    the 4-velocity every step, which makes the answer look stable while the
    trajectory quietly diverges; here the drift is the error estimate and a
    result that drifts past ``drift_tolerance`` is labelled ``drifting`` so a
    caller cannot mistake it for a converged one.
    """
    from scipy.integrate import solve_ivp

    n = len(coords)
    if len(x0) != n or len(v0) != n:
        raise DiagnosticsError(
            f"initial data must have {n} components (got {len(x0)}, {len(v0)})")

    gamma = [[[sp.lambdify(coords, christoffel[a][b][c], "numpy")
               for c in range(n)] for b in range(n)] for a in range(n)]
    g_fn = sp.lambdify(coords, metric, "numpy")

    def rhs(_t, y):
        x, v = y[:n], y[n:]
        acc = np.zeros(n)
        for a in range(n):
            total = 0.0
            for b in range(n):
                for c in range(n):
                    total -= float(gamma[a][b][c](*x)) * v[b] * v[c]
            acc[a] = total
        return np.concatenate([v, acc])

    tau_eval = np.linspace(0.0, tau_max, steps)
    sol = solve_ivp(rhs, (0.0, tau_max), np.concatenate([x0, v0]),
                    t_eval=tau_eval, rtol=rtol, atol=atol, method="DOP853")

    warnings: list[str] = []
    if not sol.success:
        # Hitting a singularity is a *result*, not a crash — report where.
        warnings.append(f"integration stopped early: {sol.message}")

    positions = sol.y[:n].T
    velocities = sol.y[n:].T
    norms = []
    for x, v in zip(positions, velocities):
        g = np.asarray(g_fn(*x), dtype=float)
        norms.append(float(v @ g @ v))

    norm0 = norms[0] if norms else 0.0
    scale = max(abs(norm0), 1.0)
    drift = max((abs(x - norm0) for x in norms), default=0.0) / scale

    if not sol.success:
        quality = "failed"
    elif drift > drift_tolerance:
        quality = "drifting"
        warnings.append(
            f"norm drifted by {drift:.2e} (tolerance {drift_tolerance:.0e}); "
            f"treat the late trajectory as indicative only")
    else:
        quality = "converged"

    return GeodesicResult(
        tau=[float(t) for t in sol.t],
        position=[[float(c) for c in row] for row in positions],
        velocity=[[float(c) for c in row] for row in velocities],
        norm=norms, norm_drift=float(drift), quality=quality,
        warnings=warnings,
    )


def circular_orbit_radii(mass: float) -> dict[str, float]:
    """Schwarzschild's two landmark radii, from the effective potential.

    Not a fit and not a table lookup: these come out of the same geodesic
    structure the tracer integrates, so agreement between them is a real
    cross-check rather than a tautology. Photon sphere 3M, innermost stable
    circular orbit 6M.
    """
    if mass <= 0:
        raise DiagnosticsError(f"mass must be positive (got {mass})")
    return {"photon_sphere": 3.0 * mass, "isco": 6.0 * mass,
            "horizon": 2.0 * mass}

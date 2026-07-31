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

and geodesic deviation gives the relative acceleration between neighbouring
worldlines as aᵘ = −Eᵘ_ν ξᵛ.  ``principal`` therefore reports the eigenvalues
of **−Eᵘ_ν**, so a positive value means *stretch* and a negative one means
*squeeze*; for a body of size L the relative acceleration between its ends is
≈ |a| · L.  This is the quantity that decides whether a warp bubble is
habitable or a blender, so its sign convention is stated rather than implied.

Two things this does **not** rely on.  The trace of E is R_αβ uᵃ uᵝ, which
vanishes in vacuum for *every* uᵘ — so a zero trace says nothing about
whether the 4-velocity was normalised, and normalisation is checked directly
instead.  And E is quadratic in u, so an unnormalised 4-velocity does not
produce an obviously wrong answer; it produces a plausible one scaled by the
square of the error.

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
    known = set(coords)
    resolved: dict[sp.Symbol, float] = {}
    for key, value in at.items():
        if isinstance(key, str):
            symbol = by_name.get(key)
        else:
            # Identity, not name: Symbol("r") and Symbol("r", real=True) are
            # different symbols and substituting the wrong one is a silent
            # no-op — the exact failure this function exists to prevent, so
            # it must not sneak back in through a Symbol-keyed argument.
            symbol = key if key in known else None
        if symbol is None:
            raise DiagnosticsError(
                f"{key!r} is not a coordinate of this metric "
                f"({', '.join(sorted(by_name))}); note that assumptions are "
                f"part of a symbol's identity")
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
            # cancel, not simplify: unbudgeted simplify on a warp metric is
            # the documented way to turn a 0.4 s job into a hang, and nothing
            # downstream needs a prettier form than a cancelled quotient.
            E[mu, nu] = sp.cancel(sum(
                r_down(mu, a, nu, b) * four_velocity[a] * four_velocity[b]
                for a in range(n) for b in range(n)))
    return E


@dataclass
class TidalReport:
    """What a tidal evaluation found, with its own honesty attached."""

    components: list[list[float]]
    #: Eigenvalues of **−Eᵘ_ν**: the principal *relative accelerations* per
    #: unit separation (geodesic deviation is aᵘ = −Eᵘ_ν ξᵛ), in geometrized
    #: units (1/length²). **Positive = stretch, negative = squeeze.**
    principal: list[float]
    #: max |eigenvalue|: the worst stretch or squeeze at this event.
    max_magnitude: float
    #: Trace of E. Zero in vacuum; a free check on the whole computation.
    trace: float
    #: g(u,u) for the observer actually used — recorded so a reader can see
    #: the magnitudes were computed for a properly normalised worldline.
    observer_norm: float
    quality: str                       # "numeric"
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"components": self.components, "principal": self.principal,
                "max_magnitude": self.max_magnitude, "trace": self.trace,
                "observer_norm": self.observer_norm, "quality": self.quality,
                "warnings": list(self.warnings)}


def evaluate_tidal(riemann_up: list, metric: sp.Matrix, coords: list[sp.Symbol],
                   four_velocity: list, at: dict[sp.Symbol | str, float],
                   *, vacuum: bool = False,
                   normalisation_tolerance: float = 1e-8,
                   trace_tolerance: float = 1e-8) -> TidalReport:
    """Evaluate the tidal tensor at one event and report what it says.

    The 4-velocity is **checked against the metric at this event**: E is
    quadratic in u, so an un-normalised observer does not fail loudly, it
    quietly rescales every reported magnitude by the square of the error.
    Nothing else catches this — in particular the vacuum trace does not,
    because ``tr E = R_αβ uᵃ uᵝ`` vanishes for any u where R_αβ = 0.

    ``vacuum=True`` additionally asserts trace-freedom, as a check on the
    *curvature* rather than on the observer. Its tolerance is relative to the
    scale of E, because an absolute one is vacuous in the weak field — which
    is precisely where a warp candidate lives.
    """
    subs = _resolve_point(coords, at)
    n = metric.shape[0]
    warnings: list[str] = []

    try:
        g_num = np.array([[float(sp.N(metric[i, j].subs(subs))) for j in range(n)]
                          for i in range(n)], dtype=float)
    except (TypeError, ValueError) as exc:
        raise DiagnosticsError(
            f"metric did not evaluate to numbers at {at}: {exc}") from exc
    if not np.all(np.isfinite(g_num)):
        raise DiagnosticsError(f"metric is not finite at {at}")

    u_num = _evaluate_vector(four_velocity, subs, n, "4-velocity")
    u_norm = float(u_num @ g_num @ u_num)
    if not math.isclose(u_norm, -1.0, abs_tol=normalisation_tolerance):
        raise DiagnosticsError(
            f"4-velocity is not a unit timelike vector at {at}: "
            f"g(u,u) = {u_norm:.6g}, expected -1. E is quadratic in u, so an "
            f"un-normalised observer yields a plausible tidal magnitude that "
            f"is wrong by the square of the error — pass normalise=True to "
            f"evaluate_tidal_normalised if you want it fixed for you.")

    E = tidal_tensor_expr(riemann_up, metric, four_velocity)
    try:
        E_num = np.array([[float(sp.N(E[i, j].subs(subs))) for j in range(n)]
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

    try:
        g_inv = np.linalg.inv(g_num)
    except np.linalg.LinAlgError as exc:
        # Routine on the polar axis of any spherical chart (g_φφ = r²sin²θ).
        # A degenerate chart is a diagnostic failure, not a crash.
        raise DiagnosticsError(
            f"metric is degenerate at {at} (a coordinate singularity such as "
            f"the polar axis); evaluate in a chart that covers this event"
        ) from exc

    mixed = g_inv @ E_num
    eigenvalues = np.linalg.eigvals(mixed)
    scale = max(float(np.max(np.abs(eigenvalues.real))), 1e-300)
    if float(np.max(np.abs(eigenvalues.imag))) > 1e-9 * scale:
        # E is self-adjoint on the space orthogonal to a unit timelike u, so
        # real eigenvalues are guaranteed for valid input. If this fires the
        # numbers are meaningless, which is not a warning.
        raise DiagnosticsError(
            f"tidal eigenvalues are complex at {at} (max |Im| = "
            f"{float(np.max(np.abs(eigenvalues.imag))):.3e}); for a unit "
            f"timelike observer E is self-adjoint, so this means the metric "
            f"signature, the frame, or the curvature is wrong")

    # Geodesic deviation: a^μ = -E^μ_ν ξ^ν. Positive = stretch.
    principal = sorted(float(-x) for x in eigenvalues.real)
    trace = float(np.trace(mixed))

    if vacuum and abs(trace) > trace_tolerance * max(scale, 1e-30):
        raise DiagnosticsError(
            f"tidal tensor trace {trace:.3e} exceeds {trace_tolerance:.0e} "
            f"relative to the tidal scale {scale:.3e} in a spacetime declared "
            f"vacuum; tr E = R_αβ uᵃuᵝ must vanish where R_αβ = 0, so the "
            f"curvature is wrong")

    return TidalReport(
        components=[[float(x) for x in row] for row in E_num],
        principal=principal,
        max_magnitude=float(max(abs(x) for x in principal)),
        trace=trace,
        observer_norm=u_norm,
        quality="numeric",
        warnings=warnings,
    )


def evaluate_tidal_normalised(riemann_up: list, metric: sp.Matrix,
                              coords: list[sp.Symbol], four_velocity: list,
                              at: dict, **kwargs) -> TidalReport:
    """Normalise the 4-velocity to unit timelike, then evaluate.

    Separate from :func:`evaluate_tidal` on purpose: rescaling a caller's
    observer is a decision, and one that silently changes every magnitude it
    reports, so it is opted into rather than defaulted.
    """
    subs = _resolve_point(coords, at)
    n = metric.shape[0]
    g_num = np.array([[float(sp.N(metric[i, j].subs(subs))) for j in range(n)]
                      for i in range(n)], dtype=float)
    u_num = _evaluate_vector(four_velocity, subs, n, "4-velocity")
    norm = float(u_num @ g_num @ u_num)
    if norm >= 0:
        raise DiagnosticsError(
            f"4-velocity is not timelike at {at}: g(u,u) = {norm:.6g} >= 0; "
            f"there is no observer to normalise")
    scaled = [sp.Float(c) for c in (u_num / math.sqrt(-norm))]
    return evaluate_tidal(riemann_up, metric, coords, scaled, at, **kwargs)


def _evaluate_vector(vector: list, subs: dict, n: int, label: str) -> np.ndarray:
    if len(vector) != n:
        raise DiagnosticsError(
            f"{label} has {len(vector)} components, metric is {n}-D")
    try:
        out = np.array([float(sp.N(sp.sympify(c).subs(subs))) for c in vector],
                       dtype=float)
    except (TypeError, ValueError) as exc:
        raise DiagnosticsError(
            f"{label} did not evaluate to numbers: {exc}") from exc
    if not np.all(np.isfinite(out)):
        raise DiagnosticsError(f"{label} is not finite at the evaluation point")
    return out


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

    # Non-finite output must never reach the drift statistic: Python's max()
    # skips NaN (every comparison is False), so a trajectory that blew up
    # would report drift 0.0 and be labelled "converged" — the exact silent
    # coercion principle 2 forbids.
    if not (np.all(np.isfinite(positions)) and np.all(np.isfinite(velocities))):
        bad = int(np.count_nonzero(~np.isfinite(positions))
                  + np.count_nonzero(~np.isfinite(velocities)))
        return GeodesicResult(
            tau=[float(t) for t in sol.t],
            position=[[float(c) if math.isfinite(c) else math.nan for c in row]
                      for row in positions],
            velocity=[[float(c) if math.isfinite(c) else math.nan for c in row]
                      for row in velocities],
            norm=[], norm_drift=math.nan, quality="failed",
            warnings=[*warnings,
                      f"{bad} non-finite value(s) in the integrated worldline; "
                      f"the trajectory left the chart or hit a singularity"])

    norms, scales = [], []
    for x, v in zip(positions, velocities):
        g = np.asarray(g_fn(*x), dtype=float)
        norms.append(float(v @ g @ v))
        # Largest single term of the quadratic form. Unlike |norm| this is
        # non-zero for a null geodesic and scales the same way under
        # reparametrisation (both go as k²), so the drift ratio below is
        # affine-invariant instead of flipping label with the affine scale.
        scales.append(float(np.max(np.abs(g * np.outer(v, v)))))

    if not np.all(np.isfinite(norms)):
        return GeodesicResult(
            tau=[float(t) for t in sol.t],
            position=[[float(c) for c in row] for row in positions],
            velocity=[[float(c) for c in row] for row in velocities],
            norm=[float(x) for x in norms], norm_drift=math.nan,
            quality="failed",
            warnings=[*warnings, "the conserved norm is not finite; the "
                                 "metric is singular somewhere on this path"])

    norm0 = norms[0]
    scale = max(abs(norm0), max(scales), 1e-300)
    drift = max(abs(x - norm0) for x in norms) / scale

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


def schwarzschild_landmark_radii(mass: float) -> dict[str, float]:
    """Schwarzschild's landmark radii, as published closed forms.

    These are **literals from the Schwarzschild solution**, not something
    derived here and not valid for any other metric — an earlier version of
    this docstring claimed otherwise, which would have made a test that
    asserts them against themselves look like validation.

    Their value is as an *independent* reference: they come from the
    published effective-potential analysis (Wald §6.3), while
    :func:`trace_geodesic` integrates the Christoffels. Comparing the two is
    a real cross-check precisely because neither is computed from the other,
    and ``test_the_tracer_reproduces_the_isco`` does exactly that.
    """
    if mass <= 0:
        raise DiagnosticsError(f"mass must be positive (got {mass})")
    return {"photon_sphere": 3.0 * mass, "isco": 6.0 * mass,
            "horizon": 2.0 * mass}

"""Pointwise energy-condition evaluation over sampled observers.

Energy conditions are statements quantified over *all* timelike/null vectors,
so a sampled evaluation can only ever return:

* ``confirmed_violation``  — a sampled observer measured a value below
  −tolerance (a single counterexample suffices);
* ``no_violation_detected`` — every sample was ≥ −tolerance (NOT a proof);
* ``inconclusive``          — sampling was too sparse or produced non-finite
  values at some points;
* ``failed``                — the computation itself broke down.

Observer families:

* Eulerian: unit normal to t=const slices (evaluated on the full grid,
  providing the heatmap-ready energy-density field);
* sampled timelike / sampled null: random boosts of the local orthonormal
  tetrad, deterministic under the experiment seed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

TOL_DEFAULT = 1e-9


@dataclass
class ConditionResult:
    condition: str  # NEC | WEC | SEC | DEC
    status: str     # confirmed_violation | no_violation_detected | inconclusive | failed
    min_value: float | None
    violation_fraction: float | None   # fraction of sampled (point, observer) pairs violating
    violating_point_fraction: float | None  # fraction of sampled grid points with any violation
    samples: int
    observers: str
    tolerance: float
    notes: list[str] = field(default_factory=list)


@dataclass
class EnergyConditionReport:
    results: dict[str, ConditionResult]
    eulerian_energy_density: np.ndarray | None  # full-grid field for heatmaps
    sampled_indices: np.ndarray | None


def _build_tetrad(g: np.ndarray, ginv: np.ndarray) -> np.ndarray | None:
    """Orthonormal tetrad e[a]^μ at one point via Gram–Schmidt.

    e[0] is the Eulerian unit normal; e[1..3] span the spatial slice.
    Returns None if the metric at this point does not admit the construction
    (wrong signature, non-finite entries, spacelike t=const slice).
    """
    n = g.shape[0]
    if not (np.all(np.isfinite(g)) and np.all(np.isfinite(ginv))):
        return None
    if ginv[0, 0] >= 0:  # t=const slice not spacelike here
        return None
    alpha = 1.0 / np.sqrt(-ginv[0, 0])
    e0 = -alpha * ginv[:, 0]  # n^μ = g^{μν} n_ν with n_ν = (−α, 0, …)

    def dot(a, b):
        return a @ g @ b

    tetrad = [e0]
    for i in range(1, n):
        v = np.zeros(n)
        v[i] = 1.0
        # project out previous tetrad legs (e0 timelike: sign flip)
        v = v + dot(v, tetrad[0]) * tetrad[0]
        for j in range(1, len(tetrad)):
            v = v - dot(v, tetrad[j]) * tetrad[j]
        norm2 = dot(v, v)
        if not np.isfinite(norm2) or norm2 <= 1e-30:
            return None
        tetrad.append(v / np.sqrt(norm2))
    return np.stack(tetrad)  # shape (n, n): tetrad[a][μ]


def _sample_vectors(tetrad: np.ndarray, kind: str, count: int, rng: np.random.Generator) -> np.ndarray:
    """Random unit timelike or null vectors from a tetrad at one point."""
    n = tetrad.shape[0]
    dirs = rng.normal(size=(count, n - 1))
    dirs /= np.linalg.norm(dirs, axis=1, keepdims=True)
    spatial = dirs @ tetrad[1:]  # (count, n) coordinate components
    if kind == "null":
        return tetrad[0][None, :] + spatial
    chi = rng.uniform(0.0, 2.0, size=count)  # rapidity range: up to γ ≈ 3.76
    return np.cosh(chi)[:, None] * tetrad[0][None, :] + np.sinh(chi)[:, None] * spatial


def evaluate_energy_conditions(
    g_arr: np.ndarray,        # (n, n, *grid)
    ginv_arr: np.ndarray,
    T_arr: np.ndarray,        # (n, n, *grid), geometrized T_{μν}
    conditions: list[str],
    sample_points: int = 512,
    observer_samples: int = 16,
    tolerance: float = TOL_DEFAULT,
    seed: int = 0,
) -> EnergyConditionReport:
    n = g_arr.shape[0]
    grid_shape = g_arr.shape[2:]
    npts = int(np.prod(grid_shape)) if grid_shape else 1

    gf = g_arr.reshape(n, n, npts)
    ginvf = ginv_arr.reshape(n, n, npts)
    Tf = T_arr.reshape(n, n, npts)

    # Full-grid Eulerian energy density (heatmap field): ρ = T_{μν} n^μ n^ν
    with np.errstate(all="ignore"):
        alpha2 = -1.0 / ginvf[0, 0]
        n_upper = -np.sqrt(np.where(alpha2 > 0, alpha2, np.nan)) * ginvf[:, 0]  # (n, npts)
        rho = np.einsum("ip,ijp,jp->p", n_upper, Tf, n_upper)
    rho_grid = rho.reshape(grid_shape) if grid_shape else rho

    rng = np.random.default_rng(seed)
    k = min(sample_points, npts)
    idx = rng.choice(npts, size=k, replace=False)

    trace = np.einsum("ijp,ijp->p", ginvf, Tf)  # T = g^{μν} T_{μν}

    # accumulators per condition
    acc: dict[str, dict] = {
        c: {"min": np.inf, "viol": 0, "total": 0, "viol_points": 0, "bad_points": 0}
        for c in conditions
    }

    for p in idx:
        g_p, ginv_p, T_p = gf[:, :, p], ginvf[:, :, p], Tf[:, :, p]
        tetrad = _build_tetrad(g_p, ginv_p)
        if tetrad is None or not np.all(np.isfinite(T_p)):
            for c in conditions:
                acc[c]["bad_points"] += 1
            continue
        null_v = _sample_vectors(tetrad, "null", observer_samples, rng)
        time_v = np.vstack([tetrad[0][None, :],
                            _sample_vectors(tetrad, "timelike", observer_samples, rng)])

        for c in conditions:
            a = acc[c]
            if c == "NEC":
                vals = np.einsum("ki,ij,kj->k", null_v, T_p, null_v)
            elif c == "WEC":
                vals = np.einsum("ki,ij,kj->k", time_v, T_p, time_v)
            elif c == "SEC":
                M = T_p - 0.5 * trace[p] * g_p
                vals = np.einsum("ki,ij,kj->k", time_v, M, time_v)
            elif c == "DEC":
                wec = np.einsum("ki,ij,kj->k", time_v, T_p, time_v)
                # flux F^μ = −g^{μα} T_{αν} u^ν must be non-spacelike
                F = -np.einsum("ma,an,kn->km", ginv_p, T_p, time_v)
                fnorm = np.einsum("km,mn,kn->k", F, g_p, F)
                vals = np.minimum(wec, -fnorm)  # violation iff wec<0 or fnorm>0
            else:
                continue
            if not np.all(np.isfinite(vals)):
                a["bad_points"] += 1
                continue
            a["min"] = min(a["min"], float(vals.min()))
            nv = int((vals < -tolerance).sum())
            a["viol"] += nv
            a["total"] += len(vals)
            a["viol_points"] += 1 if nv else 0

    results = {}
    for c in conditions:
        a = acc[c]
        notes = []
        if a["bad_points"]:
            notes.append(f"{a['bad_points']}/{k} sampled points unusable (non-finite or bad tetrad)")
        if a["total"] == 0:
            status = "failed" if a["bad_points"] == k else "inconclusive"
            results[c] = ConditionResult(
                condition=c, status=status, min_value=None, violation_fraction=None,
                violating_point_fraction=None, samples=0,
                observers="eulerian+sampled", tolerance=tolerance, notes=notes,
            )
            continue
        usable_points = k - a["bad_points"]
        if a["viol"] > 0:
            status = "confirmed_violation"
        elif a["bad_points"] > 0.2 * k or usable_points < 8:
            status = "inconclusive"
            notes.append("insufficient clean sampling to report no-violation")
        else:
            status = "no_violation_detected"
        results[c] = ConditionResult(
            condition=c, status=status, min_value=a["min"],
            violation_fraction=a["viol"] / a["total"],
            violating_point_fraction=a["viol_points"] / max(usable_points, 1),
            samples=a["total"], observers="eulerian+sampled",
            tolerance=tolerance, notes=notes,
        )

    return EnergyConditionReport(
        results=results, eulerian_energy_density=rho_grid, sampled_indices=idx,
    )

"""Numerical evaluation of symbolic geometry on coordinate grids.

The symbolic pipeline produces exact expressions; this module evaluates them
pointwise with NumPy.  Because derivatives are taken symbolically, grid values
are exact up to floating point — resolution studies therefore probe *sampling*
sensitivity (did the grid miss a feature?), and the finite-difference residual
check probes internal consistency of the symbolic derivatives.

Failure policy: NaN/Inf anywhere in an evaluated field marks that field
``failed`` and records the offending fraction — values are never masked,
clipped, or interpolated over.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import sympy as sp

from forge_geometry.entities import GridSpec


class GridEvaluationError(RuntimeError):
    pass


@dataclass
class FieldResult:
    name: str
    values: np.ndarray
    finite: bool
    nonfinite_fraction: float
    warnings: list[str] = field(default_factory=list)


@dataclass
class GridEvaluation:
    axes: dict[str, np.ndarray]          # varying coordinate name -> 1-D axis
    shape: tuple[int, ...]
    slice_values: dict[str, float]       # fixed coordinates
    fields: dict[str, FieldResult]
    metric: np.ndarray | None = None       # shape (n, n, *grid)
    inverse_metric: np.ndarray | None = None

    def field_or_raise(self, name: str) -> np.ndarray:
        f = self.fields[name]
        if not f.finite:
            raise GridEvaluationError(
                f"field {name!r} contains non-finite values "
                f"({f.nonfinite_fraction:.2%} of samples); refusing to use it"
            )
        return f.values


def build_grid(coords: list[sp.Symbol], spec: GridSpec) -> tuple[dict[str, np.ndarray], list[np.ndarray]]:
    """Return (axes, meshes) where meshes has one array per coordinate, in
    coordinate order, each broadcast to the full grid shape."""
    names = [c.name for c in coords]
    varying = [n for n in names if n in spec.bounds]
    missing = [n for n in names if n not in spec.bounds and n not in spec.slice_values]
    if missing:
        raise GridEvaluationError(
            f"coordinates {missing} have neither bounds nor a slice value"
        )
    axes: dict[str, np.ndarray] = {}
    for n in varying:
        lo, hi = spec.bounds[n]
        if not (np.isfinite(lo) and np.isfinite(hi)) or hi <= lo:
            raise GridEvaluationError(f"invalid bounds for {n}: ({lo}, {hi})")
        res = spec.resolution.get(n, 64)
        if not (2 <= res <= 4096):
            raise GridEvaluationError(f"resolution for {n} must be in [2, 4096], got {res}")
        axes[n] = np.linspace(lo, hi, res)

    mesh_varying = np.meshgrid(*[axes[n] for n in varying], indexing="ij")
    grid_shape = mesh_varying[0].shape if mesh_varying else ()
    meshes = []
    k = 0
    for n in names:
        if n in axes:
            meshes.append(mesh_varying[k])
            k += 1
        else:
            meshes.append(np.full(grid_shape, spec.slice_values[n], dtype=np.float64))
    return axes, meshes


def _lambdify(expr: sp.Expr, coords: list[sp.Symbol]):
    return sp.lambdify(coords, expr, modules=["numpy"])


def evaluate_expression(
    expr: sp.Expr, coords: list[sp.Symbol], meshes: list[np.ndarray], name: str
) -> FieldResult:
    fn = _lambdify(expr, coords)
    with np.errstate(all="ignore"):
        raw = fn(*meshes)
    values = np.broadcast_to(np.asarray(raw, dtype=np.float64), meshes[0].shape).copy()
    finite_mask = np.isfinite(values)
    frac_bad = 1.0 - float(finite_mask.mean()) if values.size else 0.0
    warnings = []
    if frac_bad > 0:
        warnings.append(
            f"{name}: {frac_bad:.2%} of grid samples are NaN/Inf "
            "(possible singularity, coordinate artifact, or domain violation)"
        )
    return FieldResult(
        name=name, values=values, finite=frac_bad == 0.0,
        nonfinite_fraction=frac_bad, warnings=warnings,
    )


def evaluate_matrix(
    m: sp.Matrix, coords: list[sp.Symbol], meshes: list[np.ndarray], name: str
) -> tuple[np.ndarray, list[FieldResult]]:
    n = m.shape[0]
    out = np.empty((n, n) + meshes[0].shape, dtype=np.float64)
    results = []
    for i in range(n):
        for j in range(n):
            fr = evaluate_expression(m[i, j], coords, meshes, f"{name}[{i}{j}]")
            out[i, j] = fr.values
            results.append(fr)
    return out, results


def evaluate_on_grid(
    coords: list[sp.Symbol],
    spec: GridSpec,
    scalar_fields: dict[str, sp.Expr],
    metric: sp.Matrix | None = None,
    inverse_metric: sp.Matrix | None = None,
) -> GridEvaluation:
    """Evaluate named scalar fields (and optionally g, g⁻¹) on the grid."""
    axes, meshes = build_grid(coords, spec)
    fields: dict[str, FieldResult] = {}
    for fname, expr in scalar_fields.items():
        fields[fname] = evaluate_expression(expr, coords, meshes, fname)

    g_arr = ginv_arr = None
    if metric is not None:
        g_arr, comps = evaluate_matrix(metric, coords, meshes, "g")
        for fr in comps:
            if not fr.finite:
                fields[fr.name] = fr
    if inverse_metric is not None:
        ginv_arr, comps = evaluate_matrix(inverse_metric, coords, meshes, "g_inv")
        for fr in comps:
            if not fr.finite:
                fields[fr.name] = fr

    return GridEvaluation(
        axes=axes, shape=meshes[0].shape, slice_values=dict(spec.slice_values),
        fields=fields, metric=g_arr, inverse_metric=ginv_arr,
    )


def eulerian_observer(g_arr: np.ndarray, ginv_arr: np.ndarray) -> np.ndarray:
    """Unit timelike normal n^μ to constant-t hypersurfaces, per grid point.

    n_μ = (−α, 0, 0, 0) with lapse α = 1/√(−g^{tt});  n^μ = g^{μν} n_ν.
    Requires g^{tt} < 0 (t=const slices spacelike); returns NaN components
    where that fails so the caller's finiteness checks trip.
    """
    gtt_up = ginv_arr[0, 0]
    with np.errstate(all="ignore"):
        alpha = 1.0 / np.sqrt(-gtt_up)
        n_lower = np.zeros_like(g_arr[0])  # shape (n, *grid) via broadcasting below
        n_lower = np.stack([-alpha] + [np.zeros_like(alpha)] * (g_arr.shape[0] - 1))
        n_upper = np.einsum("ij...,j...->i...", ginv_arr, n_lower)
    return n_upper

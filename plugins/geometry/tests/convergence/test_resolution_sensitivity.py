"""Resolution-sensitivity checks.

Derivatives are symbolic, so grid values are pointwise-exact; what resolution
changes is *sampling* of features (e.g. the thin bubble wall).  A summary
statistic that keeps drifting as resolution doubles means the grid has not
resolved the feature and results at that resolution must be marked unstable.
"""

import numpy as np
import pytest

from forge_geometry.entities import GridSpec
from forge_math import compute_geometry
from forge_math.numeric import build_grid, evaluate_matrix
from forge_metrics import builtin_metrics, load_metric_file

pytestmark = pytest.mark.convergence


def alcubierre_min_density(resolution: int) -> float:
    pm = load_metric_file(builtin_metrics()["alcubierre"])
    geo = compute_geometry(pm.matrix, pm.coords, simplify_level="none",
                           compute_kretschmann=False)
    subs = {pm.params["v"]: 0.5, pm.params["R"]: 1.0, pm.params["sigma"]: 4.0}
    spec = GridSpec(
        bounds={"x": (-2.5, 2.5), "y": (-2.5, 2.5)},
        resolution={"x": resolution, "y": resolution},
        slice_values={"t": 0.0, "z": 0.0},
    )
    _, meshes = build_grid(pm.coords, spec)
    T_arr, fields = evaluate_matrix(geo.stress_energy.subs(subs), pm.coords, meshes, "T")
    assert all(f.finite for f in fields)
    ginv_arr, _ = evaluate_matrix(geo.inverse_metric.subs(subs), pm.coords, meshes, "g_inv")
    alpha = np.sqrt(-1.0 / ginv_arr[0, 0])
    n_up = -alpha * ginv_arr[:, 0]
    rho = np.einsum("i...,ij...,j...->...", n_up, T_arr, n_up)
    return float(rho.min())


def test_alcubierre_min_density_converges_with_resolution():
    """min ρ over the slice must stabilize as resolution doubles.
    σ = 4 gives a wall a well-resolved few grid cells wide at res 96."""
    coarse = alcubierre_min_density(48)
    fine = alcubierre_min_density(96)
    finest = alcubierre_min_density(192)
    drift_ff = abs(finest - fine) / abs(finest)
    # Note: drift in a grid *extremum* is not monotone in resolution (it
    # depends on where samples land relative to the wall), so we assert
    # stability at the finest level rather than monotone decrease.
    assert abs(fine - coarse) / abs(finest) < 0.05
    assert drift_ff < 0.02, (
        f"min density still drifting at finest resolution: {coarse:.5g} → "
        f"{fine:.5g} → {finest:.5g}; result would be marked UNRESOLVED"
    )


def test_underresolved_wall_is_detectably_unstable():
    """A pathologically steep wall (σ=40) on a coarse grid must show large
    drift — this is the signal the platform uses to mark results unstable.
    Guards against convergence checks that always pass."""
    pm = load_metric_file(builtin_metrics()["alcubierre"])
    geo = compute_geometry(pm.matrix, pm.coords, simplify_level="none",
                           compute_kretschmann=False)
    subs = {pm.params["v"]: 0.5, pm.params["R"]: 1.0, pm.params["sigma"]: 40.0}

    def min_rho(res):
        spec = GridSpec(bounds={"x": (-2.5, 2.5)}, resolution={"x": res},
                        slice_values={"t": 0.0, "y": 0.5, "z": 0.0})
        _, meshes = build_grid(pm.coords, spec)
        T_arr, _ = evaluate_matrix(geo.stress_energy.subs(subs), pm.coords, meshes, "T")
        ginv_arr, _ = evaluate_matrix(geo.inverse_metric.subs(subs), pm.coords, meshes, "g_inv")
        alpha = np.sqrt(-1.0 / ginv_arr[0, 0])
        n_up = -alpha * ginv_arr[:, 0]
        return float(np.einsum("i...,ij...,j...->...", n_up, T_arr, n_up).min())

    drift = abs(min_rho(16) - min_rho(32)) / abs(min_rho(512))
    assert drift > 0.05, "expected visible under-resolution drift at σ=40, res 16→32"

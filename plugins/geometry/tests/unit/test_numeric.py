"""Grid evaluation: NaN policy, bounds validation, observer construction."""

import numpy as np
import pytest
import sympy as sp

from forge_geometry.entities import GridSpec
from forge_math.numeric import GridEvaluationError, build_grid, evaluate_on_grid
from forge_metrics import builtin_metrics, load_metric_file


def schwarzschild_geo():
    pm = load_metric_file(builtin_metrics()["schwarzschild"])
    M = pm.params["M"]
    g = pm.matrix.subs(M, 1)
    return pm, g


def test_field_crossing_horizon_flags_nonfinite():
    """g_11 = 1/(1−2M/r) blows up at r = 2M; the evaluator must report it,
    not mask it."""
    pm, g = schwarzschild_geo()
    spec = GridSpec(
        bounds={"r": (1.0, 3.0)}, resolution={"r": 41},
        slice_values={"t": 0.0, "theta": np.pi / 2, "phi": 0.0},
    )
    ev = evaluate_on_grid(pm.coords, spec, {"g11": g[1, 1]})
    fr = ev.fields["g11"]
    assert not fr.finite
    assert fr.nonfinite_fraction > 0
    with pytest.raises(GridEvaluationError, match="non-finite"):
        ev.field_or_raise("g11")


def test_exterior_grid_is_clean_and_matches_closed_form():
    pm, g = schwarzschild_geo()
    r = next(c for c in pm.coords if c.name == "r")
    spec = GridSpec(
        bounds={"r": (3.0, 10.0)}, resolution={"r": 33},
        slice_values={"t": 0.0, "theta": np.pi / 2, "phi": 0.0},
    )
    ev = evaluate_on_grid(pm.coords, spec, {"kretschmann": 48 / r**6})
    vals = ev.field_or_raise("kretschmann")
    assert np.allclose(vals, 48.0 / ev.axes["r"] ** 6)


def test_missing_slice_value_rejected():
    pm, _ = schwarzschild_geo()
    spec = GridSpec(bounds={"r": (3.0, 4.0)}, resolution={"r": 8}, slice_values={"t": 0.0})
    with pytest.raises(GridEvaluationError, match="neither bounds nor a slice value"):
        build_grid(pm.coords, spec)


@pytest.mark.parametrize("bounds", [(3.0, 3.0), (4.0, 3.0), (0.0, float("inf"))])
def test_bad_bounds_rejected(bounds):
    t, x = sp.symbols("t x", real=True)
    spec = GridSpec(bounds={"x": bounds}, resolution={"x": 8}, slice_values={"t": 0.0})
    with pytest.raises(GridEvaluationError, match="bounds"):
        build_grid([t, x], spec)


def test_resolution_limits_enforced():
    t, x = sp.symbols("t x", real=True)
    spec = GridSpec(bounds={"x": (0.0, 1.0)}, resolution={"x": 100000}, slice_values={"t": 0.0})
    with pytest.raises(GridEvaluationError, match="resolution"):
        build_grid([t, x], spec)

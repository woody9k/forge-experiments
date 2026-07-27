"""Metric definition loading: schema validation, symmetry, hashing."""

import pytest

from forge_metrics import builtin_metrics, load_metric_definition, load_metric_file
from forge_metrics.loader import MetricLoadError


def minimal(**overrides):
    base = {
        "name": "testmetric",
        "version": "1.0.0",
        "dimensions": 2,
        "coordinates": ["t", "x"],
        "signature": "-+",
        "metric": {"g_00": "-1", "g_01": "0", "g_11": "1"},
    }
    base.update(overrides)
    return base


def test_loads_all_builtin_metrics():
    metrics = builtin_metrics()
    assert set(metrics) >= {"minkowski", "schwarzschild", "alcubierre", "natario"}
    for path in metrics.values():
        pm = load_metric_file(path)
        assert pm.matrix.shape[0] == pm.definition.dimensions


def test_content_hash_is_deterministic_and_sensitive():
    a = load_metric_definition(minimal()).definition.hash
    b = load_metric_definition(minimal()).definition.hash
    c = load_metric_definition(minimal(metric={"g_00": "-2", "g_01": "0", "g_11": "1"})).definition.hash
    assert a == b
    assert a != c


def test_missing_component_rejected():
    with pytest.raises(MetricLoadError, match="missing metric component"):
        load_metric_definition(minimal(metric={"g_00": "-1", "g_01": "0", "g_10": "0"}))


def test_asymmetric_components_rejected():
    with pytest.raises(MetricLoadError, match="symmetric"):
        load_metric_definition(minimal(
            metric={"g_00": "-1", "g_01": "x", "g_10": "2*x", "g_11": "1"}
        ))


def test_dimension_coordinate_mismatch_rejected():
    with pytest.raises(MetricLoadError, match="coordinates"):
        load_metric_definition(minimal(coordinates=["t", "x", "y"]))


def test_schema_rejects_extra_fields():
    with pytest.raises(MetricLoadError, match="schema"):
        load_metric_definition(minimal(evil_field="yes"))


def test_parameter_shadowing_coordinate_rejected():
    with pytest.raises(MetricLoadError, match="shadow"):
        load_metric_definition(minimal(
            parameters={"speed": {"symbol": "x", "default": 1.0}}
        ))


def test_parameter_bounds_enforced_on_substitution():
    pm = load_metric_file(builtin_metrics()["schwarzschild"])
    with pytest.raises(MetricLoadError, match="below minimum"):
        pm.substituted({"mass": -1.0})


# ------------------------------------------------------------- default_grid

def test_default_grid_parsed_from_all_builtins():
    for name, path in builtin_metrics().items():
        pm = load_metric_file(path)
        dg = pm.definition.default_grid
        assert dg is not None, f"{name} has no default_grid"
        assert set(dg.vary) | set(dg.fix) == set(pm.definition.coordinates)
        assert not set(dg.vary) & set(dg.fix)
    # the point of the feature: schwarzschild defaults sample the exterior
    sch = load_metric_file(builtin_metrics()["schwarzschild"]).definition.default_grid
    lo, hi = sch.vary["r"]
    assert lo > 2.0 and hi > lo  # r > 2M at the default mass M=1
    tlo, thi = sch.vary["theta"]
    assert 0.0 < tlo and thi < 3.1416  # clear of the polar degeneracies


def test_default_grid_is_optional():
    assert load_metric_definition(minimal()).definition.default_grid is None


def test_default_grid_unknown_coordinate_rejected():
    with pytest.raises(MetricLoadError, match="unknown coordinates"):
        load_metric_definition(minimal(
            default_grid={"vary": {"q": [0.0, 1.0]}, "fix": {"t": 0.0, "x": 0.0}}))


def test_default_grid_vary_fix_overlap_rejected():
    with pytest.raises(MetricLoadError, match="both vary and fix"):
        load_metric_definition(minimal(
            default_grid={"vary": {"x": [0.0, 1.0]}, "fix": {"t": 0.0, "x": 0.0}}))


def test_default_grid_incomplete_coverage_rejected():
    with pytest.raises(MetricLoadError, match="missing"):
        load_metric_definition(minimal(default_grid={"vary": {"x": [0.0, 1.0]}}))


def test_default_grid_inverted_range_rejected():
    with pytest.raises(MetricLoadError, match="min < max"):
        load_metric_definition(minimal(
            default_grid={"vary": {"x": [1.0, -1.0]}, "fix": {"t": 0.0}}))


def test_default_grid_does_not_change_content_hash():
    without = load_metric_definition(minimal()).definition.hash
    with_grid = load_metric_definition(minimal(
        default_grid={"vary": {"x": [-1.0, 1.0]}, "fix": {"t": 0.0}})).definition.hash
    assert without == with_grid

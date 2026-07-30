"""Tests for the reference plugin — and a demonstration of what a plugin
author should test.

Three layers, deliberately separated:

1. the **domain model**, with no Forge involved (fast, and where the physics
   lives);
2. the **contract**, via the conformance harness (one call);
3. the **integration**, driving the platform's API with the plugin installed.
"""

from __future__ import annotations

import sys

import pytest

from forge_pendulum.model import PendulumSpec, integrate, small_angle_period_s


# ------------------------------------------------------------ domain model

def test_small_angle_period_matches_the_closed_form():
    # a 1 m pendulum swings in ~2.006 s; the formula is the known answer
    assert small_angle_period_s(1.0) == pytest.approx(2.0064093, abs=1e-6)


def test_small_amplitude_reproduces_the_closed_form():
    result = integrate(PendulumSpec(length_m=1.0, initial_angle_deg=5.0,
                                    duration_s=20.0))
    assert result.quality == "numerical_approximation"
    assert abs(result.relative_deviation) < 1e-3
    assert result.energy_drift < 1e-3
    assert result.warnings == []


def test_large_amplitude_swings_slower_by_the_known_factor():
    """A 90° pendulum's period is 1.1803x the small-angle value (Bessel
    expansion).  This is the example's real known-answer check."""
    result = integrate(PendulumSpec(length_m=1.0, initial_angle_deg=90.0,
                                    duration_s=20.0))
    assert result.relative_deviation == pytest.approx(0.1803, abs=2e-3)


def test_damping_does_not_break_the_measurement():
    result = integrate(PendulumSpec(length_m=1.0, initial_angle_deg=10.0,
                                    damping=0.05, duration_s=20.0))
    assert result.measured_period_s is not None
    assert result.max_angle_deg <= 10.0 + 1e-6  # amplitude only decays


def test_too_short_a_run_is_unresolved_not_wrong():
    """Explicit uncertainty: no period is measurable, so the result says so
    instead of returning a plausible number."""
    result = integrate(PendulumSpec(length_m=1.0, initial_angle_deg=5.0,
                                    duration_s=0.5))
    assert result.quality == "unresolved"
    assert result.measured_period_s is None
    assert "too few to measure" in result.warnings[0]


@pytest.mark.parametrize("kwargs,message", [
    ({"length_m": 0}, "length must be positive"),
    ({"initial_angle_deg": 0}, "within ±170"),
    ({"initial_angle_deg": 200}, "within ±170"),
    ({"damping": -1}, "cannot be negative"),
    ({"timestep_s": 0.5}, "timestep must be in"),
    ({"duration_s": 0}, "duration must be positive"),
])
def test_invalid_specs_fail_loudly(kwargs, message):
    spec_kwargs = {"length_m": 1.0, "initial_angle_deg": 5.0, **kwargs}
    with pytest.raises(ValueError, match=message):
        integrate(PendulumSpec(**spec_kwargs))


# ---------------------------------------------------------------- contract

def test_plugin_conforms():
    """The whole plugin contract, in one assertion."""
    from forge_pendulum.plugin import plugin
    from forge_sdk.testing import check_plugin

    report = check_plugin(plugin)
    assert report.ok, report.render()
    assert report.warnings == [], report.render()


def test_selftest_suite_and_its_verification_agree():
    from forge_pendulum.selftests import _verify, run_pendulum_selftest

    evidence = run_pendulum_selftest()
    assert evidence["passed"] is True
    assert _verify(evidence) == []


def test_coordinator_rejects_tampered_selftest_evidence():
    """A worker cannot declare itself fit: the coordinator re-checks the
    reported numbers, so flipping `passed` is not enough."""
    from forge_pendulum.selftests import _verify, run_pendulum_selftest

    evidence = run_pendulum_selftest()
    for check in evidence["checks"]:
        if check["name"] == "period_matches_golden":
            check["measured_period_s"] = 1.0     # a lie
    assert _verify(evidence), "tampered evidence must be refused"


# ------------------------------------------------------------- integration

def _reloadable(module_name: str) -> bool:
    return (module_name.startswith("apps.")
            or module_name.startswith("forge_pendulum.app"))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_EAGER", "1")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/pendulum.db")
    monkeypatch.setenv("EXPERIMENTS_DIR", str(tmp_path / "experiments"))
    monkeypatch.setenv("FORGE_DATA_DIR", str(tmp_path / "data"))
    for mod in [m for m in list(sys.modules) if _reloadable(m)]:
        del sys.modules[mod]
    from fastapi.testclient import TestClient
    from apps.api.main import app
    return TestClient(app)


def test_api_predict_run_and_read_back(client):
    predicted = client.get("/api/v1/pendulum/predict?length_m=2.0").json()
    assert predicted["quality"] == "exact_analytic"

    created = client.post("/api/v1/pendulum/runs", json={
        "length_m": 2.0, "initial_angle_deg": 4.0, "duration_s": 20.0})
    assert created.status_code == 202
    run_id = created.json()["id"]

    run = client.get(f"/api/v1/pendulum/runs/{run_id}").json()
    assert run["status"] == "completed"
    assert run["validation"]["status"] == "passed"
    # the measured period should be near the prediction for a small swing
    assert run["result"]["measured_period_s"] == pytest.approx(
        predicted["small_angle_period_s"], rel=2e-3)
    assert run_id in [r["id"] for r in client.get("/api/v1/pendulum/runs").json()]


def test_large_amplitude_is_recorded_inapplicable_not_passed(client):
    created = client.post("/api/v1/pendulum/runs", json={
        "length_m": 1.0, "initial_angle_deg": 90.0, "duration_s": 20.0})
    run = client.get(f"/api/v1/pendulum/runs/{created.json()['id']}").json()
    assert run["validation"]["status"] == "inapplicable"
    assert run["result"]["relative_deviation"] > 0.15


def test_bundle_is_written_with_checksums(client, tmp_path):
    created = client.post("/api/v1/pendulum/runs", json={
        "length_m": 1.0, "initial_angle_deg": 5.0, "duration_s": 20.0})
    run_id = created.json()["id"]

    from forge_pendulum.app.runner import read_bundle_manifest

    manifest = read_bundle_manifest(run_id)
    assert manifest["plugin"] == "pendulum"
    assert set(manifest["artifact_checksums"]) == {
        "spec.json", "result.json", "validation.json"}
    assert manifest["validation_summary"] == {"total": 1, "passed": 1}


def test_bundle_read_rejects_path_traversal(client):
    from forge_pendulum.app.runner import read_bundle_manifest

    with pytest.raises(ValueError, match="invalid run id"):
        read_bundle_manifest("../../etc")


def test_invalid_run_request_is_rejected(client):
    response = client.post("/api/v1/pendulum/runs", json={
        "length_m": -1.0, "initial_angle_deg": 5.0})
    assert response.status_code == 422


def test_sage_tool_refuses_a_nonsense_length(client):
    """A SAGE tool's arguments come from a model: validate, never trust."""
    from apps.coordinator.sage_tools import ToolExecutionError  # noqa: F401
    from forge_pendulum.app.sage_tools import (
        PendulumToolError, _predict_pendulum_period,
    )

    with pytest.raises(PendulumToolError):
        _predict_pendulum_period(None, {"length_m": "not a number"})
    with pytest.raises(PendulumToolError):
        _predict_pendulum_period(None, {"length_m": -3})

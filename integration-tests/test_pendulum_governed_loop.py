"""A second domain runs the governed research loop (platform backlog P-4).

The §21 slice in ``test_sage_slice`` proves the loop works for matter — the
domain it was originally written around.  This proves the loop is no longer
*about* matter: the same platform machinery, unchanged, runs a research
program in a domain with no mutation operators, no configurations, no
lineage, and no physics beyond a swinging weight.

If the platform ever re-learns a domain's method, this test is what breaks.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

ADMIN = {"decision": "approve", "decided_by": "director", "notes": "ok"}


def _reloadable(module_name: str) -> bool:
    return (module_name.startswith("apps.")
            or module_name.startswith("forge_pendulum.app"))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_EAGER", "1")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/pendulum-loop.db")
    monkeypatch.setenv("EXPERIMENTS_DIR", str(tmp_path / "experiments"))
    monkeypatch.setenv("FORGE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FORGE_SAGE_PROVIDER", "mock")
    for mod in [m for m in list(sys.modules) if _reloadable(m)]:
        del sys.modules[mod]
    from fastapi.testclient import TestClient
    from apps.api.main import app
    with TestClient(app) as client:
        yield client, tmp_path


def _designer_script(tmp_path, monkeypatch) -> None:
    """Script the designer to plan a *pendulum* experiment.

    Three arms, to exercise N-way comparison: a small-amplitude baseline and
    two larger candidates, where the domain's known answer says the period
    grows with amplitude.
    """
    script = {"designer": [{"output": {
        "rationale": "hold length fixed, vary release amplitude",
        "steps": [
            {"kind": "baseline", "domain": "pendulum",
             "payload": {"length_m": 1.0, "initial_angle_deg": 5.0,
                         "duration_s": 20.0}},
            {"kind": "candidate", "domain": "pendulum",
             "payload": {"length_m": 1.0, "initial_angle_deg": 45.0,
                         "duration_s": 20.0}},
            {"kind": "candidate", "domain": "pendulum",
             "payload": {"length_m": 1.0, "initial_angle_deg": 90.0,
                         "duration_s": 20.0}},
        ],
        "baselines": ["baseline"],
        "comparison_strategy": "measured period vs the small-angle closed form",
        "validations": ["period measurable", "energy drift below 1e-3"],
        "estimated_cpu_core_hours": 0.001,
    }}]}
    path = tmp_path / "pendulum-script.json"
    path.write_text(json.dumps(script))
    monkeypatch.setenv("FORGE_SAGE_MOCK_SCRIPT", str(path))
    from apps.coordinator import sage_gateway
    sage_gateway.reset_provider_cache()


def _program(client) -> dict:
    body = {
        "name": "pendulum-amplitude", "autonomy_level": 1,
        "objective": "does release amplitude change a pendulum's period?",
        "budget_limits": {"model_tokens": 200000, "max_loop_iterations": 5},
    }
    r = client.post("/api/v1/sage/programs", json=body,
                    headers={"x-idempotency-key": "pendulum-prog"})
    assert r.status_code == 201, r.text
    prog = r.json()["program"]
    r = client.post(f"/api/v1/sage-admin/programs/{prog['id']}/activate",
                    json=ADMIN)
    assert r.status_code == 200, r.text
    return prog


def test_a_pendulum_program_runs_the_whole_governed_loop(env, monkeypatch):
    client, tmp_path = env
    _designer_script(tmp_path, monkeypatch)
    prog = _program(client)

    # 1. Planner proposes; the run blocks on the human hypothesis gate.
    r = client.post(f"/api/v1/sage/programs/{prog['id']}/runs",
                    headers={"x-idempotency-key": "run-1"})
    assert r.status_code == 201, r.text
    run_id = r.json()["run"]["id"]
    state = client.post(f"/api/v1/sage/runs/{run_id}/step").json()
    assert state["waiting_for"] == "hypothesis_approval"

    hyps = client.get(f"/api/v1/sage/programs/{prog['id']}/hypotheses").json()
    client.post(f"/api/v1/sage-admin/hypotheses/{hyps[0]['id']}/review",
                json=ADMIN)

    # 2. Designer plans three pendulum arms; the run blocks on the plan gate.
    state = client.post(f"/api/v1/sage/runs/{run_id}/step").json()
    assert state["waiting_for"] == "human_approval"
    plans = client.get(f"/api/v1/sage/programs/{prog['id']}/plans").json()
    plan = plans[0]
    assert [s["kind"] for s in plan["experiment_specs"]] == [
        "baseline", "candidate", "candidate"]

    approvals = client.get("/api/v1/sage-admin/approvals").json()
    client.post(f"/api/v1/sage-admin/approvals/{approvals[0]['id']}/decide",
                json=ADMIN)

    # 3. Execute → verify → interpret → claim, driven by pendulum's protocol.
    seen = []
    for _ in range(6):
        state = client.post(f"/api/v1/sage/runs/{run_id}/step").json()
        seen.append((state["run"]["state"], state["trace"]))
        if state["run"]["state"] in ("promote", "stop", "completed"):
            break
    assert state["run"]["state"] in ("promote", "completed"), seen

    # every arm produced a real pendulum run, verified before it was used
    runs = client.get("/api/v1/pendulum/runs").json()
    assert len(runs) == 3
    assert all(r["status"] == "completed" for r in runs)

    # a level-1 claim rests on verified evidence from every candidate arm
    claims = client.get(f"/api/v1/sage/programs/{prog['id']}/claims").json()
    assert len(claims) == 1
    claim = claims[0]
    assert claim["level"] == 1
    detail = client.get(f"/api/v1/sage/claims/{claim['id']}").json()
    evidence = detail["evidence"]
    assert len(evidence) == 3          # one baseline link + two candidates
    relationships = {e["relationship"] for e in evidence}
    assert relationships == {"baseline_for", "supports"}
    # every link carries what pendulum re-derived from its own bundle
    assert all(e["source_type"] == "pendulum_run" for e in evidence)
    assert all(e["artifact_checksum"] for e in evidence)


def test_the_comparison_the_analyst_saw_is_the_domains_own(env, monkeypatch):
    """The platform passes the domain's comparison through untouched — it
    does not compute, interpret, or reshape it."""
    client, tmp_path = env
    _designer_script(tmp_path, monkeypatch)
    prog = _program(client)

    r = client.post(f"/api/v1/sage/programs/{prog['id']}/runs",
                    headers={"x-idempotency-key": "run-1"})
    run_id = r.json()["run"]["id"]
    client.post(f"/api/v1/sage/runs/{run_id}/step")
    hyps = client.get(f"/api/v1/sage/programs/{prog['id']}/hypotheses").json()
    client.post(f"/api/v1/sage-admin/hypotheses/{hyps[0]['id']}/review", json=ADMIN)
    client.post(f"/api/v1/sage/runs/{run_id}/step")
    approvals = client.get("/api/v1/sage-admin/approvals").json()
    client.post(f"/api/v1/sage-admin/approvals/{approvals[0]['id']}/decide",
                json=ADMIN)
    for _ in range(6):
        state = client.post(f"/api/v1/sage/runs/{run_id}/step").json()
        if state["run"]["state"] in ("promote", "stopped", "completed"):
            break

    runs = client.get(f"/api/v1/sage/programs/{prog['id']}/model-runs").json()
    analyst = [m for m in runs if m["role"] == "analyst"]
    assert analyst, "the analyst role should have been invoked"

    # The physics the domain reported: period grows with amplitude, and the
    # 90° arm deviates from the closed form by ~18% (the textbook value).
    pendulum_runs = client.get("/api/v1/pendulum/runs").json()
    by_angle = {}
    for row in pendulum_runs:
        detail = client.get(f"/api/v1/pendulum/runs/{row['id']}").json()
        by_angle[detail["spec"]["initial_angle_deg"]] = detail["result"]
    assert by_angle[5.0]["measured_period_s"] < by_angle[45.0]["measured_period_s"]
    assert by_angle[45.0]["measured_period_s"] < by_angle[90.0]["measured_period_s"]
    assert by_angle[90.0]["relative_deviation"] == pytest.approx(0.180, abs=2e-3)


def test_a_plan_naming_an_uninstalled_domain_fails_loudly(env, monkeypatch):
    """The honest failure mode: no protocol, no run — with a message that
    names the domain and points at the Plugins page."""
    from apps.coordinator import sage_protocol

    with pytest.raises(sage_protocol.NoExperimentProtocol) as exc:
        sage_protocol.resolve("astronomy")
    message = str(exc.value)
    assert "astronomy" in message
    assert "pendulum" in message      # lists what *is* installed
    assert "/api/v1/plugins" in message

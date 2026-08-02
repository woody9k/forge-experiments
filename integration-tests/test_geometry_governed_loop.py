"""The geometry domain runs the governed research loop (platform backlog P-9).

Before this, geometry contributed zero experiment protocols, so
``sage_protocol.resolve("geometry")`` raised and a geometry research program
died at ``design``.  The domain with the actual physics in it was the one
SAGE could not investigate — matter and pendulum could, and neither has a
spacetime in it.

What makes this the *interesting* domain rather than a third copy of the same
proof is that geometry's comparison has a real verdict to deliver: the
integrated energy in three measures with its chart sensitivity (B-16), and
two dimensional refusals that a wrong implementation would happily paper
over with a plausible number.

Runs use a small grid on purpose.  The assertions are about the loop and the
verdict's *shape*, and the symbolic phase dominates the cost either way.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

ADMIN = {"decision": "approve", "decided_by": "director", "notes": "ok"}

#: Both arms share this grid.  Same bounds and resolution in both arms is a
#: precondition of the comparison, not a convenience — see the chart and
#: dimension refusals in ``forge_geometry.app.protocol``.
GRID = {"bounds": {"x": [-2.0, 2.0], "y": [-2.0, 2.0]},
        "resolution": {"x": 12, "y": 12},
        "slice_values": {"t": 0.0, "z": 0.0}}


def _reloadable(module_name: str) -> bool:
    return (module_name.startswith("apps.")
            or module_name.startswith("forge_geometry.app"))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_EAGER", "1")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/geometry-loop.db")
    monkeypatch.setenv("EXPERIMENTS_DIR", str(tmp_path / "experiments"))
    monkeypatch.setenv("FORGE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FORGE_SAGE_PROVIDER", "mock")
    for mod in [m for m in list(sys.modules) if _reloadable(m)]:
        del sys.modules[mod]
    from fastapi.testclient import TestClient
    from apps.api.main import app
    with TestClient(app) as client:
        yield client, tmp_path


def _alcubierre_hash() -> str:
    from forge_metrics import builtin_metrics, load_metric_file

    return load_metric_file(builtin_metrics()["alcubierre"]).definition.hash


def _designer_script(tmp_path, monkeypatch, steps=None) -> None:
    """Script the designer to plan a *geometry* experiment.

    Two arms on the same metric and the same grid, differing only in wall
    steepness — which is what a geometry experiment varies. There is no
    mutation operator in this domain.
    """
    metric_hash = _alcubierre_hash()
    script = {"designer": [{"output": {
        "rationale": "hold velocity and radius fixed, vary the wall steepness",
        "steps": steps if steps is not None else [
            {"kind": "baseline", "domain": "geometry",
             "payload": {"metric_hash": metric_hash, "grid": GRID,
                         "parameter_values": {"velocity": 0.5, "radius": 1.0,
                                              "wall_steepness": 8.0}}},
            {"kind": "candidate", "domain": "geometry",
             "payload": {"metric_hash": metric_hash, "grid": GRID,
                         "parameter_values": {"velocity": 0.5, "radius": 1.0,
                                              "wall_steepness": 12.0}}},
        ],
        "baselines": ["baseline"],
        "comparison_strategy": "integrated negative energy in all three "
                               "measures, plus chart sensitivity",
        "validations": ["eulerian energy density matches Alcubierre eq. 19",
                        "negative energy present in the bubble wall"],
        "estimated_cpu_core_hours": 0.01,
    }}]}
    path = tmp_path / "geometry-script.json"
    path.write_text(json.dumps(script))
    monkeypatch.setenv("FORGE_SAGE_MOCK_SCRIPT", str(path))
    from apps.coordinator import sage_gateway
    sage_gateway.reset_provider_cache()


def _program(client) -> dict:
    body = {
        "name": "wall-steepness-sweep", "autonomy_level": 1,
        "objective": "how does the exotic-energy requirement scale with the "
                     "Alcubierre wall steepness, and how much of the answer "
                     "is the chart?",
        "allowed_metric_hashes": [_alcubierre_hash()],
        "budget_limits": {"model_tokens": 200000, "max_loop_iterations": 5},
    }
    r = client.post("/api/v1/sage/programs", json=body,
                    headers={"x-idempotency-key": "geometry-prog"})
    assert r.status_code == 201, r.text
    prog = r.json()["program"]
    r = client.post(f"/api/v1/sage-admin/programs/{prog['id']}/activate",
                    json=ADMIN)
    assert r.status_code == 200, r.text
    return prog


def _drive_to_plan_gate(client, prog) -> str:
    r = client.post(f"/api/v1/sage/programs/{prog['id']}/runs",
                    headers={"x-idempotency-key": "run-1"})
    assert r.status_code == 201, r.text
    run_id = r.json()["run"]["id"]

    state = client.post(f"/api/v1/sage/runs/{run_id}/step").json()
    assert state["waiting_for"] == "hypothesis_approval"
    hyps = client.get(f"/api/v1/sage/programs/{prog['id']}/hypotheses").json()
    client.post(f"/api/v1/sage-admin/hypotheses/{hyps[0]['id']}/review",
                json=ADMIN)
    return run_id


def _approve_and_finish(client, prog, run_id):
    state = client.post(f"/api/v1/sage/runs/{run_id}/step").json()
    assert state["waiting_for"] == "human_approval", state
    approvals = client.get("/api/v1/sage-admin/approvals").json()
    client.post(f"/api/v1/sage-admin/approvals/{approvals[0]['id']}/decide",
                json=ADMIN)

    seen = []
    for _ in range(6):
        state = client.post(f"/api/v1/sage/runs/{run_id}/step").json()
        seen.append((state["run"]["state"], state["trace"]))
        if state["run"]["state"] in ("promote", "stop", "completed"):
            break
    return state, seen


# --------------------------------------------------------------- the loop

def test_a_geometry_program_runs_the_whole_governed_loop(env, monkeypatch):
    client, tmp_path = env
    _designer_script(tmp_path, monkeypatch)
    prog = _program(client)
    run_id = _drive_to_plan_gate(client, prog)
    state, seen = _approve_and_finish(client, prog, run_id)

    assert state["run"]["state"] in ("promote", "completed"), seen

    # Every arm produced a real experiment, through the same runner the
    # human-facing API uses, and each one completed.
    experiments = client.get("/api/v1/experiments").json()
    assert len(experiments) == 2
    assert all(e["status"] == "completed" for e in experiments)

    # A level-1 claim rests on verified evidence from both arms.
    claims = client.get(f"/api/v1/sage/programs/{prog['id']}/claims").json()
    assert len(claims) == 1
    assert claims[0]["level"] == 1
    detail = client.get(f"/api/v1/sage/claims/{claims[0]['id']}").json()
    evidence = detail["evidence"]
    assert len(evidence) == 2
    assert {e["relationship"] for e in evidence} == {"baseline_for", "supports"}
    # The artifact type is what lets a stored claim find the protocol that
    # can re-verify it later.
    assert all(e["source_type"] == "geometry_experiment" for e in evidence)
    assert all(e["artifact_checksum"] for e in evidence)


def test_the_verdict_is_three_measures_and_never_one_number(env, monkeypatch):
    """What `compare` says about two spacetimes — the question that parked
    P-9. It says the integrated energy in every measure it could compute,
    the chart sensitivity, and no aggregate."""
    client, tmp_path = env
    _designer_script(tmp_path, monkeypatch)
    prog = _program(client)
    run_id = _drive_to_plan_gate(client, prog)
    _approve_and_finish(client, prog, run_id)

    from apps.coordinator import sage_protocol

    protocol = sage_protocol.resolve("geometry")
    experiments = client.get("/api/v1/experiments").json()
    by_steepness = {
        client.get(f"/api/v1/experiments/{e['id']}").json()
        ["parameter_values"]["wall_steepness"]: e["id"] for e in experiments}
    verdict = protocol.compare(
        None, {"baseline": by_steepness[8.0], "candidate": by_steepness[12.0]})

    assert set(verdict["arms"]) == {"baseline", "candidate"}
    for row in verdict["arms"].values():
        assert set(row["integrals"]) == {"coordinate", "proper", "adm"}
        assert row["integrals"]["coordinate"]["available"] is True
        assert row["integrals"]["adm"]["available"] is False
        assert row["integrals"]["adm"]["total"] is None      # never 0.0
        assert row["chart_sensitivity"] == 1.0  # Alcubierre's slice is flat

    comparison = verdict["comparisons"]["candidate"]
    assert comparison["comparable"] is True
    # Both measures reported separately, and nothing combines them: no key
    # anywhere in the verdict's data offers a single headline number.
    assert set(comparison["measures"]) == {"coordinate", "proper"}

    def _keys(node):
        if isinstance(node, dict):
            for key, value in node.items():
                yield key
                yield from _keys(value)
        elif isinstance(node, list):
            for value in node:
                yield from _keys(value)

    # `verdict_basis` is prose that says "never aggregated", so grepping the
    # serialized blob would match its own disclaimer — check the keys.
    assert not {k for k in _keys(verdict)
                if k in ("aggregate", "score", "fitness", "combined")}
    # A steeper wall is a thinner shell: the negative energy changes, and the
    # test asserts the comparison *carries* that rather than its sign, which
    # is a physics result and belongs in the validation suite.
    assert comparison["measures"]["proper"]["negative_part_change"] != 0.0


# ------------------------------------------------------- the two refusals

def test_arms_in_different_charts_are_reported_but_not_differenced(env,
                                                                   monkeypatch):
    """Alcubierre against Natário: both numbers, no delta.

    A 2-D total is per unit length of the suppressed direction only when
    that direction's length element is the coordinate differential — true
    for Cartesian suppressing `z`, false for spherical suppressing `phi`
    (limitations 9a). Subtracting them would produce a plausible number in
    the wrong units, which is the exact failure this platform exists to
    avoid.
    """
    client, tmp_path = env
    from forge_metrics import builtin_metrics, load_metric_file

    natario = load_metric_file(builtin_metrics()["natario"]).definition
    natario_grid = {"bounds": {"r": [0.1, 3.0], "theta": [0.1, 3.04]},
                    "resolution": {"r": 12, "theta": 12},
                    "slice_values": {"t": 0.0, "phi": 0.0}}
    _designer_script(tmp_path, monkeypatch, steps=[
        {"kind": "baseline", "domain": "geometry",
         "payload": {"metric_hash": _alcubierre_hash(), "grid": GRID,
                     "parameter_values": {"velocity": 0.5, "radius": 1.0,
                                          "wall_steepness": 8.0}}},
        {"kind": "candidate", "domain": "geometry",
         "payload": {"metric_hash": natario.hash, "grid": natario_grid,
                     "parameter_values": {"velocity": 0.5, "radius": 1.0,
                                          "wall_steepness": 8.0}}},
    ])
    body = {
        "name": "cross-chart", "autonomy_level": 1,
        "objective": "does zero expansion cost more exotic matter?",
        "allowed_metric_hashes": [_alcubierre_hash(), natario.hash],
        "budget_limits": {"model_tokens": 200000, "max_loop_iterations": 5},
    }
    r = client.post("/api/v1/sage/programs", json=body,
                    headers={"x-idempotency-key": "cross-chart-prog"})
    prog = r.json()["program"]
    client.post(f"/api/v1/sage-admin/programs/{prog['id']}/activate", json=ADMIN)
    run_id = _drive_to_plan_gate(client, prog)
    _approve_and_finish(client, prog, run_id)

    from apps.coordinator import sage_protocol

    protocol = sage_protocol.resolve("geometry")
    experiments = client.get("/api/v1/experiments").json()
    by_metric = {e["metric_name"]: e["id"] for e in experiments}
    verdict = protocol.compare(None, {"baseline": by_metric["alcubierre"],
                                      "candidate": by_metric["natario"]})

    comparison = verdict["comparisons"]["candidate"]
    assert comparison["comparable"] is False
    assert "different charts" in comparison["reason"]
    assert "limitations 9a" in comparison["reason"]
    # Refused to subtract, not refused to report: both arms' physics is there.
    for row in verdict["arms"].values():
        assert row["integrals"]["coordinate"]["negative_part"] < 0.0
    # And the chart sensitivities differ, which is the finding this
    # comparison *can* honestly deliver.
    assert (verdict["arms"]["baseline"]["chart_sensitivity"]
            != verdict["arms"]["candidate"]["chart_sensitivity"])


def test_an_arm_with_no_grid_is_reported_as_having_no_integral(env, monkeypatch):
    """A gridless run is a legitimate experiment, not a failure — its
    symbolic tensors and known-answer validations still ran. It just cannot
    take part in an energy comparison, and says so."""
    client, tmp_path = env
    _designer_script(tmp_path, monkeypatch, steps=[
        {"kind": "baseline", "domain": "geometry",
         "payload": {"metric_hash": _alcubierre_hash(), "grid": GRID,
                     "parameter_values": {"velocity": 0.5, "radius": 1.0,
                                          "wall_steepness": 8.0}}},
        {"kind": "candidate", "domain": "geometry",
         "payload": {"metric_hash": _alcubierre_hash(),
                     "parameter_values": {"velocity": 0.5, "radius": 1.0,
                                          "wall_steepness": 12.0}}},
    ])
    prog = _program(client)
    run_id = _drive_to_plan_gate(client, prog)
    _approve_and_finish(client, prog, run_id)

    from apps.coordinator import sage_protocol

    protocol = sage_protocol.resolve("geometry")
    experiments = client.get("/api/v1/experiments").json()
    gridless = [e["id"] for e in experiments
                if client.get(f"/api/v1/experiments/{e['id']}").json()["grid"] is None]
    gridded = [e["id"] for e in experiments if e["id"] not in gridless]
    assert len(gridless) == 1 and len(gridded) == 1

    verdict = protocol.compare(None, {"baseline": gridded[0],
                                      "candidate": gridless[0]})
    row = verdict["arms"]["candidate"]
    assert row["integrals"] is None
    assert "sampled no grid" in row["integrals_reason"]
    assert verdict["comparisons"]["candidate"]["comparable"] is False


# ------------------------------------------------------------ policy gate

def test_a_metric_outside_the_allowlist_is_refused_at_design_time(env,
                                                                  monkeypatch):
    """Fail-early, before a human is asked to approve anything. The tool
    layer refuses it again at submission — this only moves the refusal
    earlier."""
    client, tmp_path = env
    from forge_metrics import builtin_metrics, load_metric_file

    schwarzschild = load_metric_file(
        builtin_metrics()["schwarzschild"]).definition
    _designer_script(tmp_path, monkeypatch, steps=[
        {"kind": "baseline", "domain": "geometry",
         "payload": {"metric_hash": _alcubierre_hash(), "grid": GRID,
                     "parameter_values": {"velocity": 0.5, "radius": 1.0,
                                          "wall_steepness": 8.0}}},
        {"kind": "candidate", "domain": "geometry",
         "payload": {"metric_hash": schwarzschild.hash,
                     "parameter_values": {"mass": 1.0}}},
    ])
    prog = _program(client)          # allowlists Alcubierre only
    run_id = _drive_to_plan_gate(client, prog)

    state = client.post(f"/api/v1/sage/runs/{run_id}/step").json()
    assert state["run"]["state"] == "stop"
    assert "not allowlisted" in json.dumps(state)
    # Nothing ran, and no approval was ever requested of a human.
    assert client.get("/api/v1/experiments").json() == []
    assert client.get("/api/v1/sage-admin/approvals").json() == []

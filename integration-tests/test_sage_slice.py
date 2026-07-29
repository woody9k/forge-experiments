"""End-to-end SAGE vertical slice (acceptance plan §16) + restart safety.

The exact scenario from the architecture spec §21, driven over HTTP with the
deterministic mock model:

    seed program → planner hypothesis → human approves → designer creates
    baseline+mutation plan → skeptic critiques → human approves the unchanged
    plan hash → exactly two matter analyses run through the real funnel →
    coordinator re-verifies both bundles → analyst compares → skeptic
    challenges → level-1 evidence-linked claim → archivist summary →
    restart/replay duplicates nothing.
"""

from __future__ import annotations


def _reloadable(module_name: str) -> bool:
    """Modules a fresh-environment fixture must drop.

    The platform's app layer *and* the plugin app layers: plugin modules
    bind platform services (store session, bundle paths) at import time, so
    dropping only ``apps.*`` leaves plugin modules pointing at the previous
    test's engine — which is silent cross-test contamination, not an error.
    """
    return (module_name.startswith("apps.")
            or module_name.startswith("forge_geometry.app")
            or module_name.startswith("forge_matter.app"))


import forge_matter.app.store as mstore  # platform-split: matter rows are plugin-owned

import json
import sys

import pytest

CASIMIR_GENOME = {
    "name": "casimir_stack_slice", "version": "0.1.0",
    "description": "SAGE slice: 2 gold plates, 100 nm gap, 1 cm^2",
    "coordinate_system": {"type": "cartesian", "units": "SI"},
    "quantum_boundaries": [{
        "id": "stack", "type": "parallel_plate_array",
        "plate_count": 2, "plate_area_m2": 1e-4, "separation_m": 1e-7,
        "plate_thickness_m": 1e-4, "material_model": "ideal_conductor",
        "plate_material_id": "gold", "temperature_k": 0.0,
    }],
    "observation_regions": [
        {"id": "center", "type": "point", "position": [0, 0, 0]}],
}

ADMIN = {"decision": "approve", "decided_by": "director@example.org"}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_EAGER", "1")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/sage-slice.db")
    monkeypatch.setenv("EXPERIMENTS_DIR", str(tmp_path / "experiments"))
    monkeypatch.setenv("FORGE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FORGE_SAGE_PROVIDER", "mock")
    monkeypatch.delenv("FORGE_SAGE_MOCK_SCRIPT", raising=False)
    for mod in [m for m in list(sys.modules) if _reloadable(m)]:
        del sys.modules[mod]
    from fastapi.testclient import TestClient
    from apps.api.main import app
    with TestClient(app) as client:
        yield client, tmp_path


def _seed_configuration() -> str:
    """The trusted baseline configuration — human-provided input, not SAGE's."""
    from apps.coordinator import store
    from forge_matter.compiler import load_configuration
    config = load_configuration(CASIMIR_GENOME)
    mstore.save_matter_configuration(config)
    return config.id


def _designer_script(tmp_path, monkeypatch, config_id: str,
                     extra: dict | None = None) -> None:
    script = {
        "designer": [{"output": {
            "rationale": "baseline vs halved separation, identical funnel",
            "steps": [
                {"kind": "baseline", "configuration_id": config_id},
                {"kind": "mutation", "configuration_id": config_id,
                 "mutation_operator": "alter_separation",
                 "mutation_target": "stack", "parameters": {"factor": 0.5}},
            ],
            "baselines": ["baseline"],
            "comparison_strategy": "paired effects via compare_with_parent",
            "validations": ["funnel gates 0-2 completed"],
            "estimated_cpu_core_hours": 0.01,
        }}],
    }
    script.update(extra or {})
    path = tmp_path / "slice-script.json"
    path.write_text(json.dumps(script))
    monkeypatch.setenv("FORGE_SAGE_MOCK_SCRIPT", str(path))
    from apps.coordinator import sage_gateway
    sage_gateway.reset_provider_cache()


def _bootstrap_program(client, config_id: str, **overrides) -> dict:
    body = {
        "name": "casimir-slice", "objective": "reduce exotic energy",
        "autonomy_level": 1,
        "allowed_matter_versions": [config_id],
        "allowed_mutation_operators": ["alter_separation"],
        "budget_limits": {"model_tokens": 200000, "max_loop_iterations": 5},
    }
    body.update(overrides)
    r = client.post("/api/v1/sage/programs", json=body,
                    headers={"x-idempotency-key": "prog"})
    assert r.status_code == 201, r.text
    prog = r.json()["program"]
    r = client.post(f"/api/v1/sage-admin/programs/{prog['id']}/activate", json=ADMIN)
    assert r.status_code == 200, r.text
    return prog


def _start_and_step(client, prog_id: str, key="run-1") -> dict:
    r = client.post(f"/api/v1/sage/programs/{prog_id}/runs",
                    headers={"x-idempotency-key": key})
    assert r.status_code == 201, r.text
    run = r.json()["run"]
    return client.post(f"/api/v1/sage/runs/{run['id']}/step").json()


def test_full_vertical_slice_with_restart(env, monkeypatch):
    client, tmp_path = env
    from apps.coordinator import store

    # 1-2. Seed config + Level-1 program, activated by the director.
    config_id = _seed_configuration()
    _designer_script(tmp_path, monkeypatch, config_id)
    prog = _bootstrap_program(client, config_id)

    # 3. Planner proposes; the run blocks on the human hypothesis gate.
    state = _start_and_step(client, prog["id"])
    run_id = state["run"]["id"]
    assert state["waiting_for"] == "hypothesis_approval"
    hyps = client.get(f"/api/v1/sage/programs/{prog['id']}/hypotheses").json()
    assert len(hyps) == 1 and hyps[0]["status"] == "proposed"

    # 4. Human approves the hypothesis.
    r = client.post(f"/api/v1/sage-admin/hypotheses/{hyps[0]['id']}/review",
                    json=ADMIN)
    assert r.json()["status"] == "approved"

    # 5-6. Designer plans, skeptic critiques, policy requests approval; the
    # run blocks on the human plan gate with the plan hash bound.
    state = client.post(f"/api/v1/sage/runs/{run_id}/step").json()
    assert state["waiting_for"] == "human_approval"
    plans = client.get(f"/api/v1/sage/programs/{prog['id']}/plans").json()
    assert len(plans) == 1 and plans[0]["status"] == "awaiting_approval"
    critiques = client.get(f"/api/v1/sage/programs/{prog['id']}/critiques").json()
    assert len(critiques) == 1  # plan critique persisted
    approvals = client.get("/api/v1/sage-admin/approvals").json()
    assert len(approvals) == 1
    assert approvals[0]["target_hash"] == plans[0]["plan_hash"]

    # 6b. Human approves the unchanged plan hash.
    r = client.post(f"/api/v1/sage-admin/approvals/{approvals[0]['id']}/decide",
                    json=ADMIN)
    assert r.json()["status"] == "approved"

    # 7-11. Execute → validate → interpret → challenge → memory → PROMOTE.
    state = client.post(f"/api/v1/sage/runs/{run_id}/step").json()
    assert state["run"]["state"] == "promote", state
    assert "execute" in state["trace"] and "validate" in state["trace"]

    # Exactly two configurations exist: the trusted baseline and the one
    # mutated child SAGE created through the real funnel path.
    configs = mstore.list_matter_configurations()
    assert len(configs) == 2  # baseline + mutated child, nothing else
    child = [c for c in configs if c["generation"] == 1][0]
    assert child["parent_ids"] == [config_id]

    # Level-1 claim with verified evidence links; ladder enforced.
    claims = client.get(f"/api/v1/sage/programs/{prog['id']}/claims").json()
    assert len(claims) == 1
    claim = claims[0]
    assert claim["level"] == 1
    detail = client.get(f"/api/v1/sage/claims/{claim['id']}").json()
    assert len(detail["evidence"]) == 2
    rels = sorted(e["relationship"] for e in detail["evidence"])
    assert rels == ["baseline_for", "supports"]
    assert all(e["artifact_checksum"] for e in detail["evidence"])
    assert "repeated_result_within_tolerance" in detail["missing_for_next_level"]

    # Hypothesis supported; program summary versioned; both critiques stand.
    hyps = client.get(f"/api/v1/sage/programs/{prog['id']}/hypotheses").json()
    assert hyps[0]["status"] == "supported"
    prog_now = client.get(f"/api/v1/sage/programs/{prog['id']}").json()
    assert prog_now["summary_version"] == 1 and prog_now["current_summary"]
    assert len(client.get(
        f"/api/v1/sage/programs/{prog['id']}/critiques").json()) == 2

    # Decision trail covers the whole loop.
    decisions = client.get(f"/api/v1/sage/programs/{prog['id']}/decisions").json()
    kinds = [d["decision_type"] for d in decisions]
    for expected in ("observe", "propose_hypothesis", "design_plan",
                     "critique_plan", "request_approval", "execute",
                     "interpret_result", "challenge_result", "create_claim",
                     "update_memory", "promote"):
        assert expected in kinds, f"missing decision {expected}: {kinds}"

    # Budget was charged for model usage and the loop iteration.
    budget = client.get(f"/api/v1/sage/programs/{prog['id']}/budget").json()
    assert budget["usage"]["model_tokens"] > 0
    assert budget["usage"]["loop_iterations"] == 1

    # The loop's substantive changes were recorded as immutable versions (S-9),
    # attributed to the loop state or the director that caused each one.
    history = client.get(f"/api/v1/sage/programs/{prog['id']}/history").json()
    assert {v["entity_type"] for v in history} == {
        "program", "hypothesis", "plan", "claim"}
    for entity_type in ("program", "hypothesis", "plan", "claim"):
        seq = [v["version"] for v in history if v["entity_type"] == entity_type]
        assert seq == sorted(seq)          # chronological order is version order
    hyp_history = [v for v in history if v["entity_type"] == "hypothesis"]
    assert hyp_history[0]["previous_hash"] is None
    assert any(a.startswith("director:") for a in
               (v["actor"] for v in hyp_history))
    assert any(a.startswith("runtime:") for a in (v["actor"] for v in history))
    # The plan's approval transition is on the record as its own version.
    plan_versions = client.get(
        f"/api/v1/sage/history/plan/{plans[0]['id']}").json()
    statuses = [client.get(
        f"/api/v1/sage/history/plan/{plans[0]['id']}/{v['version']}"
    ).json()["payload"]["status"] for v in plan_versions]
    assert statuses[0] == "draft" and statuses[-1] == "completed"
    assert "awaiting_approval" in statuses and "approved" in statuses

    # 13-15. "Restart": drop in-process provider state, then replay the step
    # and the reconciler.  Nothing duplicates; terminal state is stable.
    from apps.coordinator import sage_gateway
    sage_gateway.reset_provider_cache()
    replay = client.post(f"/api/v1/sage/runs/{run_id}/step").json()
    assert replay["run"]["state"] == "promote"
    r = client.post("/api/v1/sage-admin/reconcile")
    assert r.status_code == 200

    # A replay re-saves entities idempotently; identical payloads are not
    # substantive changes, so the recorded history is byte-for-byte unchanged.
    assert client.get(
        f"/api/v1/sage/programs/{prog['id']}/history").json() == history
    assert len(client.get(f"/api/v1/sage/programs/{prog['id']}/claims").json()) == 1
    assert len(client.get(f"/api/v1/sage/programs/{prog['id']}/hypotheses").json()) == 1
    assert len(mstore.list_matter_configurations()) == 2
    runs = client.get(f"/api/v1/sage/programs/{prog['id']}/runs").json()
    assert len(runs) == 1

    # Model-run count is exactly the five roles that ran once each.
    model_runs = client.get(f"/api/v1/sage/programs/{prog['id']}/model-runs").json()
    roles = sorted(m["role"] for m in model_runs)
    assert roles == ["analyst", "archivist", "designer", "planner", "skeptic",
                     "skeptic"]


def test_default_canned_designer_reaches_the_plan_gate(env):
    """Regression: with no FORGE_SAGE_MOCK_SCRIPT (the default stack), the
    canned designer must adopt the program's allowlisted configuration so the
    plan materializes — not dead-end on a missing configuration_id."""
    client, _ = env
    config_id = _seed_configuration()
    prog = _bootstrap_program(client, config_id)
    state = _start_and_step(client, prog["id"])
    run_id = state["run"]["id"]
    assert state["waiting_for"] == "hypothesis_approval"
    hyp = client.get(f"/api/v1/sage/programs/{prog['id']}/hypotheses").json()[0]
    client.post(f"/api/v1/sage-admin/hypotheses/{hyp['id']}/review", json=ADMIN)

    state = client.post(f"/api/v1/sage/runs/{run_id}/step").json()
    assert state["waiting_for"] == "human_approval", state["run"].get("stop_reason")
    plans = client.get(f"/api/v1/sage/programs/{prog['id']}/plans").json()
    assert len(plans) == 1
    assert [s["configuration_id"] for s in plans[0]["experiment_specs"]] == \
        [config_id, config_id]


def test_changed_plan_hash_invalidates_approval(env, monkeypatch):
    client, tmp_path = env
    from apps.coordinator import store
    from forge_sage import ExperimentPlan

    config_id = _seed_configuration()
    _designer_script(tmp_path, monkeypatch, config_id)
    prog = _bootstrap_program(client, config_id)
    state = _start_and_step(client, prog["id"])
    run_id = state["run"]["id"]
    hyp = client.get(f"/api/v1/sage/programs/{prog['id']}/hypotheses").json()[0]
    client.post(f"/api/v1/sage-admin/hypotheses/{hyp['id']}/review", json=ADMIN)
    state = client.post(f"/api/v1/sage/runs/{run_id}/step").json()
    assert state["waiting_for"] == "human_approval"

    # Tamper with the plan after the approval request was created.
    plan_payload = client.get(f"/api/v1/sage/programs/{prog['id']}/plans").json()[0]
    plan = ExperimentPlan.model_validate(plan_payload)
    plan.experiment_specs[1]["parameters"]["factor"] = 0.001  # sneaky change
    plan.plan_hash = plan.compute_hash()
    store.save_plan(plan)

    # The admin decide endpoint refuses: hash no longer matches.
    approval = client.get("/api/v1/sage-admin/approvals").json()[0]
    r = client.post(f"/api/v1/sage-admin/approvals/{approval['id']}/decide",
                    json=ADMIN)
    assert r.status_code == 409
    assert "hash changed" in r.json()["detail"]


def test_skeptic_veto_stops_run_and_supersedes_plan(env, monkeypatch):
    client, tmp_path = env
    config_id = _seed_configuration()
    _designer_script(tmp_path, monkeypatch, config_id, extra={
        "skeptic": [{"output": {"verdict": "veto", "findings": [{
            "category": "resolution",
            "statement": "no convergence evidence planned",
            "severity": "veto",
            "proposed_counter_test": "add resolution study",
        }]}}]})
    prog = _bootstrap_program(client, config_id)
    state = _start_and_step(client, prog["id"])
    run_id = state["run"]["id"]
    hyp = client.get(f"/api/v1/sage/programs/{prog['id']}/hypotheses").json()[0]
    client.post(f"/api/v1/sage-admin/hypotheses/{hyp['id']}/review", json=ADMIN)
    state = client.post(f"/api/v1/sage/runs/{run_id}/step").json()

    assert state["run"]["state"] == "stop"
    assert "veto" in state["run"]["stop_reason"]
    plans = client.get(f"/api/v1/sage/programs/{prog['id']}/plans").json()
    assert plans[0]["status"] == "superseded"
    # The veto critique is durable and no analyses ran.
    critiques = client.get(f"/api/v1/sage/programs/{prog['id']}/critiques").json()
    assert critiques[0]["severity"] == "veto"
    from apps.coordinator import store
    assert mstore.list_matter_configurations() != []  # baseline config exists
    assert len(mstore.list_matter_configurations()) == 1  # but no child was made


def test_crash_resume_cannot_bypass_plan_veto(env, monkeypatch):
    """Regression (PR #3 review must-fix 1): if the process dies after the
    veto critique is persisted but before the run moves to STOP, resume must
    still STOP with the veto — never proceed into POLICY_CHECK."""
    client, tmp_path = env
    from apps.coordinator import sage_runtime, store
    from forge_sage import ResearchProgram, ResearchRun

    config_id = _seed_configuration()
    _designer_script(tmp_path, monkeypatch, config_id, extra={
        "skeptic": [{"output": {"verdict": "veto", "findings": [{
            "category": "resolution", "statement": "no convergence evidence",
            "severity": "veto", "proposed_counter_test": "resolution study",
        }]}}]})
    prog = _bootstrap_program(client, config_id)
    state = _start_and_step(client, prog["id"])
    run_id = state["run"]["id"]
    hyp = client.get(f"/api/v1/sage/programs/{prog['id']}/hypotheses").json()[0]
    client.post(f"/api/v1/sage-admin/hypotheses/{hyp['id']}/review", json=ADMIN)

    # Advance exactly one state (DESIGN -> CRITIQUE_PLAN)...
    run = ResearchRun.model_validate(store.load_research_run(run_id))
    result = sage_runtime.advance(run)
    run = result["run"]
    assert run.state.value == "critique_plan"
    # ...then run the critique handler directly and DISCARD its outcome —
    # this is the crash: critique + pointer + superseded plan are persisted,
    # but the run never moved to STOP.
    program = ResearchProgram.model_validate(store.load_program(prog["id"]))
    outcome = sage_runtime._h_critique_plan(run, program)
    assert outcome[0].value == "stop"  # the handler wanted to stop...
    assert store.load_research_run(run_id)["state"] == "critique_plan"  # ...crash

    # Resume: must cleanly STOP with the veto reason, not IllegalTransition.
    state = client.post(f"/api/v1/sage/runs/{run_id}/step").json()
    assert state["run"]["state"] == "stop"
    assert "veto" in state["run"]["stop_reason"]
    # The skeptic was not re-invoked on resume.
    skeptic_runs = [m for m in client.get(
        f"/api/v1/sage/programs/{prog['id']}/model-runs").json()
        if m["role"] == "skeptic"]
    assert len(skeptic_runs) == 1
    # And no execution happened.
    from apps.coordinator import store as st
    assert len(st.list_matter_configurations()) == 1


def test_mid_execute_crash_completes_under_reserved_id(env, monkeypatch):
    """Regression (PR #3 review must-fix 2): the ledger key is written before
    the side effect, so a crash between reserving and submitting resumes by
    completing the analysis under the reserved id — never duplicating."""
    client, tmp_path = env
    from apps.coordinator import store
    from forge_domain.entities import new_id

    config_id = _seed_configuration()
    _designer_script(tmp_path, monkeypatch, config_id)
    prog = _bootstrap_program(client, config_id)
    state = _start_and_step(client, prog["id"])
    run_id = state["run"]["id"]
    hyp = client.get(f"/api/v1/sage/programs/{prog['id']}/hypotheses").json()[0]
    client.post(f"/api/v1/sage-admin/hypotheses/{hyp['id']}/review", json=ADMIN)
    state = client.post(f"/api/v1/sage/runs/{run_id}/step").json()
    plan = client.get(f"/api/v1/sage/programs/{prog['id']}/plans").json()[0]
    approval = client.get("/api/v1/sage-admin/approvals").json()[0]
    client.post(f"/api/v1/sage-admin/approvals/{approval['id']}/decide", json=ADMIN)

    # Simulate the crashed attempt: the baseline key was reserved (with the id
    # the analysis WILL get) but the process died before submitting.
    reserved = new_id()
    store.record_idempotent(prog["id"], f"plan:{plan['id']}:analysis:baseline",
                            "matter_analysis", reserved)
    assert mstore.load_matter_analysis(reserved) is None  # nothing ran yet

    # Resume: execution completes under the reserved id; exactly two analyses.
    state = client.post(f"/api/v1/sage/runs/{run_id}/step").json()
    assert state["run"]["state"] == "promote", state
    assert mstore.load_matter_analysis(reserved) is not None
    assert mstore.load_matter_analysis(reserved)["status"] == "completed"
    assert len(mstore.list_matter_configurations()) == 2  # baseline + one child
    # The claim's baseline evidence cites the reserved id.
    claim = client.get(f"/api/v1/sage/programs/{prog['id']}/claims").json()[0]
    detail = client.get(f"/api/v1/sage/claims/{claim['id']}").json()
    baseline_ev = [e for e in detail["evidence"]
                   if e["relationship"] == "baseline_for"][0]
    assert baseline_ev["source_id"] == reserved


def test_concurrent_stepper_blocks_instead_of_duplicating(env, monkeypatch):
    """S1d in the runtime: a step whose reservation is held waits, not spends.

    Contention is not a scientific failure, so the run blocks (``waiting_for``)
    rather than transitioning to STOP, and the holder's work stands.
    """
    client, tmp_path = env
    from apps.coordinator import store
    from forge_domain.entities import new_id

    config_id = _seed_configuration()
    _designer_script(tmp_path, monkeypatch, config_id)
    prog = _bootstrap_program(client, config_id)
    r = client.post(f"/api/v1/sage/programs/{prog['id']}/runs",
                    headers={"x-idempotency-key": "run-1"})
    run_id = r.json()["run"]["id"]
    reserved = new_id()

    # Another stepper is mid-flight on this run's hypothesis reservation.
    monkeypatch.setenv("FORGE_SAGE_CLAIM_WAIT_S", "0.1")
    monkeypatch.setenv("FORGE_SAGE_CLAIM_POLL_S", "0.01")
    held = store.acquire_idempotent(prog["id"], f"run:{run_id}:hypothesis",
                                    "hypothesis", reserved)

    state = client.post(f"/api/v1/sage/runs/{run_id}/step").json()
    assert state["waiting_for"] == "concurrent_step"
    assert state["run"]["state"] == "hypothesize"  # no transition, no STOP
    assert client.get(
        f"/api/v1/sage/programs/{prog['id']}/model-runs").json() == []
    assert client.get(
        f"/api/v1/sage/programs/{prog['id']}/hypotheses").json() == []

    # Once the holder is gone the step proceeds under the reserved id.
    store.release_idempotent(held)
    monkeypatch.delenv("FORGE_SAGE_CLAIM_WAIT_S")
    state = client.post(f"/api/v1/sage/runs/{run_id}/step").json()
    assert state["waiting_for"] == "hypothesis_approval"
    hyps = client.get(f"/api/v1/sage/programs/{prog['id']}/hypotheses").json()
    assert [h["id"] for h in hyps] == [reserved]


def test_level_0_program_cannot_reach_execution(env, monkeypatch):
    client, tmp_path = env
    config_id = _seed_configuration()
    _designer_script(tmp_path, monkeypatch, config_id)
    prog = _bootstrap_program(client, config_id, autonomy_level=0)
    state = _start_and_step(client, prog["id"])
    run_id = state["run"]["id"]
    hyp = client.get(f"/api/v1/sage/programs/{prog['id']}/hypotheses").json()[0]
    client.post(f"/api/v1/sage-admin/hypotheses/{hyp['id']}/review", json=ADMIN)
    state = client.post(f"/api/v1/sage/runs/{run_id}/step").json()

    # Policy check halts the loop: L0 is advisory and cannot submit.
    assert state["run"]["state"] == "stop"
    assert "cannot submit" in state["run"]["stop_reason"]
    from apps.coordinator import store
    assert len(mstore.list_matter_configurations()) == 1  # nothing executed


def test_paused_program_blocks_immediately(env, monkeypatch):
    client, tmp_path = env
    config_id = _seed_configuration()
    _designer_script(tmp_path, monkeypatch, config_id)
    prog = _bootstrap_program(client, config_id)
    state = _start_and_step(client, prog["id"])
    run_id = state["run"]["id"]
    client.post(f"/api/v1/sage-admin/programs/{prog['id']}/pause", json=ADMIN)
    state = client.post(f"/api/v1/sage/runs/{run_id}/step").json()
    assert state["waiting_for"] == "program_resumed"
    assert state["trace"] == [state["run"]["state"]]  # nothing advanced


def test_loop_iteration_cap_exhausts_program(env, monkeypatch):
    client, tmp_path = env
    config_id = _seed_configuration()
    _designer_script(tmp_path, monkeypatch, config_id)
    prog = _bootstrap_program(
        client, config_id,
        budget_limits={"model_tokens": 200000, "max_loop_iterations": 1},
        max_loop_iterations=1)
    _start_and_step(client, prog["id"], key="run-1")
    r = client.post(f"/api/v1/sage/programs/{prog['id']}/runs",
                    headers={"x-idempotency-key": "run-2"})
    assert r.status_code == 409
    assert "cap" in r.json()["detail"] or "exhausted" in r.json()["detail"]
    prog_now = client.get(f"/api/v1/sage/programs/{prog['id']}").json()
    assert prog_now["status"] == "budget_exhausted"

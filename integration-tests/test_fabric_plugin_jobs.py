"""A plugin's jobs run on the Worker Fabric (platform backlog P-3).

The agent used to import ``forge_geometry.app.runner`` unconditionally, so
*every* fabric job was assumed to be a geometry experiment and no other
domain's work could run on the fleet at all. It reads the ``forge.worker``
entry point now, and dispatches on the job's type.

This drives the whole path for **pendulum** — a domain the platform has
never heard of — through a real agent: enrol, approve, self-test (including
the plugin's own suite), take a lease, run, upload, and have the coordinator
re-verify what came back.
"""

from __future__ import annotations

import sys

import pytest


def _reloadable(module_name: str) -> bool:
    return (module_name.startswith("apps.")
            or module_name.startswith("forge_geometry.app")
            or module_name.startswith("forge_pendulum.app"))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_EAGER", "1")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/fabric-plugin.db")
    monkeypatch.setenv("EXPERIMENTS_DIR", str(tmp_path / "experiments"))
    monkeypatch.setenv("FORGE_DATA_DIR", str(tmp_path / "data"))
    for mod in [m for m in list(sys.modules) if _reloadable(m)]:
        del sys.modules[mod]
    from fastapi.testclient import TestClient
    from apps.api.main import app
    from apps.agent.main import WorkerAgent
    with TestClient(app) as client:
        yield client, WorkerAgent, tmp_path


def _ready_agent(client, WorkerAgent, tmp_path):
    tok = client.post("/api/v1/workers/enrollment-tokens", json={}).json()
    agent = WorkerAgent(client, tmp_path / "agent", "fabric-host")
    worker_id = agent.enroll(tok["token"])
    client.post(f"/api/v1/workers/{worker_id}/approve", json={})
    assert agent.fetch_certificate()
    agent.push_inventory()
    return agent, worker_id, agent.run_selftests()


def test_the_agent_validates_on_installed_plugin_suites(env):
    """A host proves what it can do with the *plugins it has*, not with a
    list the platform hardcoded."""
    client, WorkerAgent, tmp_path = env
    _agent, worker_id, states = _ready_agent(client, WorkerAgent, tmp_path)

    assert states["baseline_execution"] == "ready"
    # geometry's suites and pendulum's, because both are installed here
    assert states["symbolic_sympy"] == "ready"
    assert states["pendulum_integration"] == "ready"

    # and the host reports which distributions it actually carries, so
    # "why was this job never placed?" is answerable without SSH
    host = client.get(f"/api/v1/workers/{worker_id}").json()
    plugins = {p["id"]: p for p in host["inventory"]["plugins"]}
    assert {"geometry", "pendulum"} <= set(plugins)
    assert plugins["pendulum"]["job_types"] == ["pendulum_run"]
    assert not any(p["error"] for p in plugins.values())


def test_a_pendulum_job_runs_on_the_fabric(env):
    """The headline: a domain the platform knows nothing about, executed by
    a real agent, verified by the coordinator."""
    client, WorkerAgent, tmp_path = env
    agent, _worker_id, _states = _ready_agent(client, WorkerAgent, tmp_path)

    from forge_domain.entities import new_id

    run_id = new_id()
    job = client.post("/api/v1/jobs", json={
        "job_type": "pendulum_run",
        "experiment": {"id": run_id,
                       "spec": {"length_m": 1.0, "initial_angle_deg": 5.0,
                                "duration_s": 10.0, "timestep_s": 1e-3}},
        "requirements": {"capabilities": ["pendulum_integration"]},
    }).json()
    assert job["status"] == "scheduled", job

    result = agent.poll_and_execute_once()
    assert result and result.get("verified") is True, result

    # the coordinator re-verified the uploaded bundle, and the attempt
    # carries the domain's own provenance rather than geometry's
    attempts = client.get(f"/api/v1/jobs/{job['id']}").json()["attempts"]
    assert len(attempts) == 1
    provenance = attempts[0]["provenance"]
    assert provenance["job_type"] == "pendulum_run"
    assert provenance["experiment_id"] == run_id
    assert provenance["validation_summary"]["passed"] == 1


def test_a_job_type_no_installed_plugin_owns_is_refused(env):
    """Honest failure on the host: name the type, list what it can run."""
    client, WorkerAgent, tmp_path = env
    agent, _worker_id, _states = _ready_agent(client, WorkerAgent, tmp_path)

    client.post("/api/v1/jobs", json={
        "job_type": "astronomy_survey",
        "experiment": {"id": "x"},
    })
    result = agent.poll_and_execute_once()
    assert result and "failed" in result
    assert "astronomy_survey" in result["error"]
    assert "pendulum_run" in result["error"]

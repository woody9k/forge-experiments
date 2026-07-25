"""``submit_geometry_experiment`` — the geometry half of the submission surface.

The tool was in the registry but unwired (limitations S1c); these tests pin the
properties it has to hold now that it is not:

* the metric allowlist is enforced by **content hash** and fails closed — an
  empty allowlist permits nothing, whatever the model asked for;
* every call, allowed or refused, leaves an audit row through ``call_tool``;
* a caller-reserved id is honoured, so the runtime's reserve-first ledger can
  hold the experiment id before the side effect and a crashed submission
  completes under the same id;
* the coordinator re-verifies the bundle from disk — SAGE submits, Warp Forge
  decides validity.

Minkowski is used throughout: it is the cheapest metric in the library, and the
properties under test are about the submission path, not the physics.
"""

from __future__ import annotations

import sys

import pytest


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_EAGER", "1")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/sage-geometry.db")
    monkeypatch.setenv("EXPERIMENTS_DIR", str(tmp_path / "experiments"))
    monkeypatch.setenv("FORGE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FORGE_SAGE_PROVIDER", "mock")
    for mod in [m for m in list(sys.modules) if m.startswith("apps.")]:
        del sys.modules[mod]
    from apps.coordinator import sage_evidence, sage_tools, store
    return store, sage_tools, sage_evidence, tmp_path


def _metric_hash(name: str = "minkowski") -> str:
    from forge_metrics import builtin_metrics, load_metric_file
    return load_metric_file(builtin_metrics()[name]).definition.hash


def _program(store, *, allowed: list[str] | None = None, level: int = 1):
    from forge_sage import AutonomyLevel, AutonomyPolicy, ResearchProgram
    from forge_sage.states import ProgramStatus
    prog = ResearchProgram(
        name="geometry-program", objective="reproduce flat space",
        policy=AutonomyPolicy(level=AutonomyLevel(level),
                              allowed_metric_hashes=allowed or []))
    prog.status = ProgramStatus.ACTIVE  # submission requires an activated program
    store.save_program(prog)
    return prog


def _submit(tools, prog, **args):
    from forge_sage import Role
    return tools.call_tool(prog, Role.DESIGNER, "submit_geometry_experiment", args)


def _audit(store, prog):
    return [r for r in store.tool_calls_for_program(prog.id)
            if r["tool"] == "submit_geometry_experiment"]


# ------------------------------------------------------------ the happy path

def test_allowlisted_metric_submits_and_is_audited(env):
    store, tools, _, _ = env
    prog = _program(store, allowed=[_metric_hash()])

    result = _submit(tools, prog, metric_name="minkowski")

    assert result["status"] == "completed"
    experiment = store.load_experiment(result["experiment_id"])
    assert experiment is not None
    assert experiment.metric_hash == _metric_hash()
    assert experiment.status.value == "completed"
    # It went through the real pipeline: results and validations were persisted.
    assert store.experiment_results(experiment.id)
    assert store.experiment_validations(experiment.id)
    # The reported summary comes from the re-read manifest, not from the caller.
    assert result["validation_summary"]["failed"] == 0

    rows = _audit(store, prog)
    assert len(rows) == 1
    assert rows[0]["allowed"] is True
    assert rows[0]["detail"]["outcome"] == "ok"


def test_metric_may_be_addressed_by_content_hash(env):
    """The allowlist is written in hashes, so the tool accepts one directly."""
    store, tools, _, _ = env
    digest = _metric_hash()
    prog = _program(store, allowed=[digest])
    result = _submit(tools, prog, metric_hash=digest)
    assert store.load_experiment(result["experiment_id"]).metric_name == "minkowski"


# --------------------------------------------------------------- fail closed

def test_non_allowlisted_metric_is_refused_and_audited(env):
    store, tools, _, _ = env
    # A real, valid metric — just not this program's.
    prog = _program(store, allowed=[_metric_hash("minkowski")])

    with pytest.raises(tools.ToolExecutionError, match="not allowlisted"):
        _submit(tools, prog, metric_name="schwarzschild")

    assert store.list_experiments() == []
    rows = _audit(store, prog)
    assert len(rows) == 1 and rows[0]["detail"]["outcome"] == "error"


def test_empty_allowlist_permits_nothing(env):
    store, tools, _, _ = env
    prog = _program(store, allowed=[])
    for name in ("minkowski", "schwarzschild", "alcubierre", "natario"):
        with pytest.raises(tools.ToolExecutionError, match="not allowlisted"):
            _submit(tools, prog, metric_name=name)
    assert store.list_experiments() == []
    assert len(_audit(store, prog)) == 4  # every refusal is on the record


def test_unknown_metric_and_missing_selector_fail_loud(env):
    store, tools, _, _ = env
    prog = _program(store, allowed=[_metric_hash()])
    with pytest.raises(tools.ToolExecutionError, match="unknown metric"):
        _submit(tools, prog, metric_name="../../etc/passwd")
    with pytest.raises(tools.ToolExecutionError, match="metric_hash or metric_name"):
        _submit(tools, prog)
    with pytest.raises(tools.ToolExecutionError, match="unknown parameters"):
        _submit(tools, prog, metric_name="minkowski",
                parameter_values={"not_a_parameter": 1.0})
    assert store.list_experiments() == []


def test_advisory_program_cannot_submit_geometry(env):
    """L0 is advisory: the policy denies before any pipeline work happens."""
    store, tools, _, _ = env
    from apps.coordinator.sage_policy import PolicyDenied
    prog = _program(store, allowed=[_metric_hash()], level=0)
    with pytest.raises(PolicyDenied):
        _submit(tools, prog, metric_name="minkowski")
    assert store.list_experiments() == []
    assert _audit(store, prog)[0]["allowed"] is False


# ------------------------------------------- reserve-first / crash recovery

def test_reserved_id_completes_after_a_simulated_crash(env):
    """The ledger holds the id before the side effect; a retry completes it."""
    store, tools, evidence, _ = env
    from forge_domain.entities import new_id
    prog = _program(store, allowed=[_metric_hash()])
    plan_id = new_id()

    # The crash: the key was reserved with the id the experiment WILL get, and
    # the process died before submitting anything.
    reserved = new_id()
    store.record_idempotent(prog.id, f"plan:{plan_id}:experiment:baseline",
                            "experiment", reserved)
    assert store.load_experiment(reserved) is None

    result = _submit(tools, prog, metric_name="minkowski",
                     experiment_id=reserved)
    assert result["experiment_id"] == reserved
    assert len(store.list_experiments()) == 1  # completed, never duplicated

    # And the coordinator can now prove ownership of it from the ledger alone.
    verified = evidence.verify_geometry_experiment(
        prog, reserved, plan_id=plan_id, step="baseline")
    assert verified["manifest"]["experiment"]["id"] == reserved


def test_malformed_reserved_id_is_refused(env):
    store, tools, _, _ = env
    prog = _program(store, allowed=[_metric_hash()])
    with pytest.raises(tools.ToolExecutionError, match="invalid id"):
        _submit(tools, prog, metric_name="minkowski",
                experiment_id="../../../etc/passwd")


# ------------------------------------------------- coordinator re-verification

def test_evidence_verification_rejects_unowned_and_tampered_bundles(env):
    store, tools, evidence, _ = env
    from apps.coordinator.runner import experiments_dir
    from forge_domain.entities import new_id
    prog = _program(store, allowed=[_metric_hash()])
    plan_id = new_id()
    reserved = new_id()
    store.record_idempotent(prog.id, f"plan:{plan_id}:experiment:baseline",
                            "experiment", reserved)
    _submit(tools, prog, metric_name="minkowski", experiment_id=reserved)

    # Ownership: the ledger, not the caller, decides which plan produced it.
    with pytest.raises(evidence.EvidenceError, match="ownership check failed"):
        evidence.verify_geometry_experiment(prog, reserved, plan_id=new_id(),
                                            step="baseline")

    # A link built from the verified artifact re-verifies from scratch...
    from forge_sage import EvidenceRelationship
    link = evidence.build_verified_link(
        prog, new_id(), reserved, EvidenceRelationship.SUPPORTS,
        plan_id=plan_id, step="baseline", source_type="experiment")
    assert link.artifact_path == f"{reserved}/manifest.json"
    evidence.verify_evidence_link(prog, link)

    # ...and stops re-verifying the moment the bytes change.
    bundle = experiments_dir() / reserved
    target = next(p for p in bundle.iterdir()
                  if p.is_file() and p.name != "manifest.json"
                  and p.name in _checksummed(bundle))
    target.write_text("tampered")
    with pytest.raises(evidence.EvidenceError, match="checksum mismatch"):
        evidence.verify_evidence_link(prog, link)


def _checksummed(bundle) -> set[str]:
    import json
    manifest = json.loads((bundle / "manifest.json").read_text())
    return set(manifest["artifact_checksums"])

"""Pendulum Lab's experiment protocol — the reference implementation.

A pendulum experiment is: release at one amplitude (the baseline), release
at others (the candidates), compare the measured periods.  No mutation, no
derived artifact, no parent-child lineage — which is the point of showing it
beside matter's: the loop accommodates both without knowing either.

Four operations, ~70 lines. That is the whole cost of joining the governed
research loop.
"""

from __future__ import annotations

from forge_sdk import ExperimentProtocol

ARTIFACT_TYPE = "pendulum_run"


def submit(ctx, arm, repeat_of=None):
    """Run one arm under the id the platform reserved.

    A repeat re-runs the *same* spec: the integration is deterministic, so a
    rerun that disagrees means something is wrong with the machine, not with
    the pendulum — which is exactly what level-2 verification is asking.
    """
    from forge_pendulum.app import store

    payload = dict(arm.payload)
    if repeat_of is not None:
        original = store.load_run(repeat_of)
        if original is None:
            raise ValueError(f"cannot repeat unknown run {repeat_of!r}")
        payload = dict(original["spec"])

    ctx.call_tool("run_pendulum_experiment", {
        "length_m": payload.get("length_m", 1.0),
        "initial_angle_deg": payload.get("initial_angle_deg", 5.0),
        "damping": payload.get("damping", 0.0),
        "duration_s": payload.get("duration_s", 20.0),
        "timestep_s": payload.get("timestep_s", 1e-3),
        "run_id": ctx.reserved_id,
    })
    return ctx.reserved_id


def exists(artifact_id: str) -> bool:
    from forge_pendulum.app import store

    return store.load_run(artifact_id) is not None


def verify(artifact_id: str, *, program=None, plan_id: str = "",
           arm: str = "") -> dict:
    """Re-derive this run's evidence rather than trusting what it reported.

    Three parts, in the order every domain's verify has them: what the
    platform proves (this program's plan submitted it), what the domain
    alone can say (it completed and it measured a period), and what the
    platform re-derives from disk (the bundle's checksums).
    """
    from apps.coordinator import sage_evidence
    from forge_pendulum.app import store

    run = store.load_run(artifact_id)
    if run is None:
        raise ValueError(f"no pendulum run {artifact_id!r}")
    if run["status"] != "completed":
        raise ValueError(f"run {artifact_id} did not complete: {run.get('error')}")
    if program is not None:
        sage_evidence.assert_owned(program, artifact_id, plan_id=plan_id,
                                   arm=arm or "arm")

    result = run["result"]
    if result.get("measured_period_s") is None:
        raise ValueError(
            f"run {artifact_id} measured no period ({'; '.join(result['warnings'])})")
    verified = sage_evidence.verify_bundle(artifact_id, artifact_id,
                                           label=f"pendulum run {artifact_id!r}")
    return {
        "artifact": artifact_id,
        "measured_period_s": result["measured_period_s"],
        "validation": run["validation"]["status"],
        **verified,
    }


def compare(ctx, artifacts, mode="arms", tolerances=None):
    from forge_pendulum.app import store

    def _result(run_id: str) -> dict:
        run = store.load_run(run_id)
        if run is None or run.get("result") is None:
            raise ValueError(f"pendulum run {run_id!r} has no result")
        return run["result"]

    if mode == "arms":
        baseline_key = next(k for k in artifacts if k.startswith("baseline"))
        baseline = _result(artifacts[baseline_key])
        rows = []
        for key, run_id in artifacts.items():
            r = _result(run_id)
            rows.append({
                "arm": key,
                "observable": "period_s",
                "value": r["measured_period_s"],
                "closed_form_s": r["small_angle_period_s"],
                "deviation_from_closed_form": r["relative_deviation"],
                "change_from_baseline": (
                    None if key == baseline_key else
                    r["measured_period_s"] - baseline["measured_period_s"]),
                "quality": r["quality"],
                "warnings": r["warnings"],
            })
        return {"baseline_arm": baseline_key, "rows": rows}

    rel = (tolerances or {}).get("relative", 0.0)
    absolute = (tolerances or {}).get("absolute", 0.0)
    out = {}
    for step, original_id in artifacts["original"].items():
        a = _result(original_id)["measured_period_s"]
        b = _result(artifacts["repeat"][step])["measured_period_s"]
        agrees = abs(a - b) <= max(abs(a) * rel, absolute)
        out[step] = {
            "agrees": agrees,
            "mismatches": [] if agrees else ["period_s"],
            "observables": {"period_s": {"original": a, "repeat": b}},
        }
    return out


def validate_arm(program, arm) -> None:
    """Reject an arm the integrator would refuse anyway — before a human is
    asked to approve the plan."""
    from forge_pendulum.model import PendulumSpec

    payload = arm.payload
    PendulumSpec(
        length_m=payload.get("length_m", 1.0),
        initial_angle_deg=payload.get("initial_angle_deg", 5.0),
        damping=payload.get("damping", 0.0),
        duration_s=payload.get("duration_s", 20.0),
        timestep_s=payload.get("timestep_s", 1e-3),
    ).validate()


PROTOCOL = ExperimentProtocol(
    domain="pendulum",
    artifact_type=ARTIFACT_TYPE,
    submit=submit,
    exists=exists,
    required_tools=("run_pendulum_experiment",),
    verify=verify,
    compare=compare,
    validate_arm=validate_arm,
    description="Release a pendulum at a baseline amplitude and at candidate "
                "amplitudes, then compare the measured periods.",
)

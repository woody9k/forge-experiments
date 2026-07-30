"""Matter's experiment protocol (platform backlog P-4).

This is the method that used to live in the platform's run state machine:
take an allowlisted baseline configuration, derive a candidate by applying
an allowlisted mutation operator, analyse both through the funnel, and
compare the candidate against its parent.

Now it lives with the domain that means it, and the loop drives it through
four operations.  Everything the platform owns — the state machine,
reserve-first idempotency, the human gates, decisions, budgets, audit —
stays where it was; nothing here decides whether an analysis is valid.
"""

from __future__ import annotations

from forge_sdk import ExperimentProtocol

ARTIFACT_TYPE = "matter_analysis"


def _analysis_store():
    from forge_matter.app import store

    return store


def submit(ctx, arm, repeat_of=None):
    """Produce one arm's analysis under the id the platform reserved.

    A candidate arm derives its configuration first (its own reservation, so
    a crash between mutating and analysing resumes without a duplicate
    lineage row), then analyses it.  A *repeat* re-analyses the configuration
    the original analysis already used: re-deriving it would add a duplicate
    lineage row for no gain, since the mutation is deterministic in its seed.
    """
    store = _analysis_store()
    payload = arm.payload

    if repeat_of is not None:
        original = store.load_matter_analysis(repeat_of)
        if original is None:
            raise ValueError(f"cannot repeat unknown analysis {repeat_of!r}")
        configuration_id = original["configuration_id"]
    elif arm.kind == "baseline":
        configuration_id = payload["configuration_id"]
    else:
        # Derive the candidate configuration, once, under its own claim.
        def _mutate(child_id: str) -> None:
            ctx.call_tool("mutate_matter_configuration", {
                "configuration_id": payload["configuration_id"],
                "operator": payload["mutation_operator"],
                "target": payload.get("mutation_target"),
                "parameters": payload.get("parameters", {}),
                "seed": ctx.seed,
                "child_id": child_id,
                "reason": f"plan arm {arm.index} mutation step",
            })

        configuration_id = ctx.reserve(
            f"plan-arm:{arm.index}:configuration", "matter_configuration",
            store.load_matter_configuration, _mutate)

    ctx.call_tool("submit_matter_analysis", {
        "configuration_id": configuration_id,
        "seed": ctx.seed,
        "analysis_id": ctx.reserved_id,
    })
    return ctx.reserved_id


def exists(artifact_id: str) -> bool:
    return _analysis_store().load_matter_analysis(artifact_id) is not None


def bundle_name(analysis_id: str) -> str:
    """Matter analyses bundle to ``<experiments>/matter-<id>/``."""
    return f"matter-{analysis_id}"


def verify(artifact_id: str, *, program=None, plan_id: str = "",
           arm: str = "") -> dict:
    """Re-verify one analysis coordinator-side.

    Moved here from the platform, which used to hold this function (and
    geometry's twin) and a table of their bundle layouts — so a claim in any
    other domain could not be built at all.  What is *matter's* to say is
    here: the analysis exists and its funnel status is ``completed``, meaning
    no gate rejected it.  What every domain needs is the platform's:
    ownership proof from the idempotency ledger and bundle re-verification.

    Raising is how a domain rejects its own artifact.
    """
    from apps.coordinator import sage_evidence

    record = _analysis_store().load_matter_analysis(artifact_id)
    if record is None:
        raise sage_evidence.EvidenceError(
            f"analysis {artifact_id!r} does not exist")
    if record.get("status") != "completed":
        raise sage_evidence.EvidenceError(
            f"analysis {artifact_id!r} status {record.get('status')!r} is not "
            f"'completed' — failed or gate-rejected results cannot support "
            f"claims")
    if program is not None:
        sage_evidence.assert_owned(program, artifact_id, plan_id=plan_id,
                                   arm=arm or "arm")

    verified = sage_evidence.verify_bundle(
        bundle_name(artifact_id), artifact_id,
        label=f"analysis {artifact_id!r}")
    manifest = verified["manifest"]
    if manifest.get("analysis_id") != artifact_id:
        raise sage_evidence.EvidenceError(
            f"manifest analysis_id {manifest.get('analysis_id')!r} does not "
            f"match {artifact_id!r}")
    return {"record": record, **verified}


def compare(ctx, artifacts, mode="arms", tolerances=None):
    from forge_matter import MatterAnalysis
    from forge_matter.app import runner

    store = _analysis_store()

    def _load(analysis_id: str) -> MatterAnalysis:
        record = store.load_matter_analysis(analysis_id)
        if record is None:
            raise runner.ComparisonError(
                f"analysis {analysis_id!r} is missing")
        return MatterAnalysis.model_validate(record)

    if mode == "arms":
        baseline_key = next(k for k in artifacts if k.startswith("baseline"))
        parent = _load(artifacts[baseline_key])
        out = {}
        for key, analysis_id in artifacts.items():
            if key == baseline_key:
                continue
            out[key] = runner.compare_with_parent(parent, _load(analysis_id))
        # One candidate is the common case; keep its comparison at the top
        # level too so an analyst prompt reads the same as it did before.
        if len(out) == 1:
            only = next(iter(out.values()))
            return {**only, "arms": out}
        return {"arms": out}

    rel = (tolerances or {}).get("relative", 0.0)
    absolute = (tolerances or {}).get("absolute", 0.0)
    return {
        step: runner.compare_within_tolerance(
            _load(original_id), _load(artifacts["repeat"][step]),
            relative_tolerance=rel, absolute_tolerance=absolute)
        for step, original_id in artifacts["original"].items()
    }


def validate_arm(program, arm) -> None:
    """Design-time policy check, in matter's vocabulary.

    Moved here from the platform's design handler, which used to read
    ``allowed_matter_versions`` and ``allowed_mutation_operators`` directly —
    domain policy names living in Forge Core.  Fail-early only: the same
    allowlists are enforced authoritatively by the SAGE tools at submission,
    which is why this can live in the plugin without weakening anything.
    """
    payload = arm.payload
    configuration_id = payload.get("configuration_id")
    if not configuration_id:
        raise ValueError(f"the {arm.kind} arm names no configuration_id")
    if configuration_id not in program.policy.allowed_matter_versions:
        raise ValueError(f"configuration {configuration_id!r} is not "
                         f"allowlisted for this program")
    if arm.kind == "candidate":
        operator = payload.get("mutation_operator")
        if operator not in program.policy.allowed_mutation_operators:
            raise ValueError(f"mutation operator {operator!r} is not "
                             f"allowlisted for this program")


def claims_undomained_plan(steps) -> bool:
    """_compat_: recognise a plan stored before the platform's P-4 change.

    Those plans name no domain, so in a deployment that has since installed
    a second domain the platform cannot tell whose they are.  A matter plan
    is one whose steps name a configuration to analyse.  Delete this when no
    stored plan predates P-4.
    """
    return any(step.get("configuration_id") for step in steps)


PROTOCOL = ExperimentProtocol(
    domain="matter",
    artifact_type=ARTIFACT_TYPE,
    submit=submit,
    exists=exists,
    required_tools=("mutate_matter_configuration", "submit_matter_analysis"),
    verify=verify,
    compare=compare,
    validate_arm=validate_arm,
    claims_undomained_plan=claims_undomained_plan,
    description="Analyse an allowlisted baseline configuration and a "
                "candidate derived from it by an allowlisted mutation "
                "operator, then compare the candidate against its parent.",
)

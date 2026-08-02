"""Geometry's experiment protocol (platform backlog P-9).

Without this file a SAGE program in the geometry domain died at ``design``:
``sage_protocol.resolve("geometry")`` raised, so the one domain with real
physics in it was the one the governed research loop could not investigate.

A geometry experiment is: evaluate a trusted metric at a baseline parameter
set (the baseline arm) and at other parameter sets (the candidate arms), then
compare what the spacetime demands. No mutation and no derived artifact —
structurally this is pendulum's shape, not matter's.

**What `compare` says about two spacetimes** was the open question that
parked P-9, on the grounds that it is a physics decision rather than a
plumbing one. B-16 answers it: the verdict is the integrated energy in all
three measures, side by side and never aggregated, plus the chart
sensitivity that says how much of the answer is the coordinate system. That
is exactly what a warp-metric comparison is *for*, and it is the only
comparison this platform can make honestly today.

Three refusals here are load-bearing, and each one exists because the
alternative produces a plausible number rather than an error:

* **Arms sampled over different numbers of dimensions are not compared.** A
  2-D slice integral is an energy per unit length and a 3-D one is an
  energy. Differencing them is wrong by a dimension.
* **Arms in different coordinate systems get no delta.** "Per unit length"
  is exact for a Cartesian run suppressing ``z`` and loose for a spherical
  one suppressing ``phi``, where the suppressed direction's length element
  is ``r sin(theta) dphi`` (limitations 9a). Both arms' numbers are still
  reported in full — the refusal is to subtract them.
* **A measure that was not computed is never zero.** It arrives as
  ``available: false`` with its reason, the same way ``forge_math.energy``
  reports it.
"""

from __future__ import annotations

import json

from forge_sdk import ExperimentProtocol

ARTIFACT_TYPE = "geometry_experiment"

#: Observables a repeat compares. The pipeline is deterministic in its spec,
#: so a rerun that disagrees on any of these is a fact about the machine.
REPEAT_OBSERVABLES = ("coordinate_total", "coordinate_negative_part",
                      "proper_total", "proper_negative_part",
                      "negative_fraction", "chart_sensitivity")


def _store():
    from forge_geometry.app import store

    return store


def _bundle_report(experiment_id: str) -> dict | None:
    """This run's ``energy_integrals.json``, or ``None`` if it has none.

    A run submitted without a grid never enters the numerical phase, so it
    has no integrals at all. That is a legitimate experiment (the symbolic
    tensors and the known-answer validations still ran), not a failure — so
    the absence is reported rather than raised on.
    """
    from forge_geometry.app.runner import experiments_dir

    root = experiments_dir().resolve()
    path = (root / experiment_id / "energy_integrals.json").resolve()
    # Containment check for the same reason the tool layer has one: the id
    # reaches here from a plan, and a plan is model output.
    if not path.is_relative_to(root) or not path.is_file():
        return None
    return json.loads(path.read_text())


# --------------------------------------------------------------- operations

def submit(ctx, arm, repeat_of=None):
    """Run one arm under the id the platform reserved.

    A repeat re-runs the *same* spec, including the same seed: the symbolic
    pipeline and the grid evaluation are both deterministic in the spec, so a
    rerun that disagrees means something is wrong with the machine rather
    than with the metric — which is exactly what level-2 verification asks.
    """
    payload = dict(arm.payload)
    if repeat_of is not None:
        original = _store().load_experiment(repeat_of)
        if original is None:
            raise ValueError(f"cannot repeat unknown experiment {repeat_of!r}")
        payload = {
            "metric_hash": original.metric_hash,
            "parameter_values": dict(original.parameter_values),
            "grid": original.grid.model_dump(mode="json") if original.grid else None,
            "seed": original.random_seed,
        }

    args = {
        "metric_hash": payload.get("metric_hash"),
        "metric_name": payload.get("metric_name"),
        "parameter_values": payload.get("parameter_values")
                            or payload.get("parameters") or {},
        "seed": payload.get("seed", ctx.seed),
        "experiment_id": ctx.reserved_id,
    }
    for optional in ("grid", "energy_conditions", "solver_backend"):
        if payload.get(optional) is not None:
            args[optional] = payload[optional]

    # Through the tool layer, never around it: the metric allowlist is
    # checked by content hash there and fails closed.
    ctx.call_tool("submit_geometry_experiment", args)
    return ctx.reserved_id


def exists(artifact_id: str) -> bool:
    return _store().load_experiment(artifact_id) is not None


def verify(artifact_id: str, *, program=None, plan_id: str = "",
           arm: str = "") -> dict:
    """Re-derive this experiment's evidence instead of trusting its report.

    Three parts, in the order every domain's verify has them: what the
    platform proves (this program's plan submitted it), what geometry alone
    can say (it completed, and no known-answer validation failed), and what
    the platform re-derives from disk (every artifact checksum).

    A *failed validation* rejects the artifact. A metric that does not
    reproduce its own published values cannot support a claim about a novel
    one, whatever the rest of the bundle says.
    """
    from apps.coordinator import sage_evidence
    from forge_geometry.app.sage_tools import verify_geometry_bundle

    experiment = _store().load_experiment(artifact_id)
    if experiment is None:
        raise sage_evidence.EvidenceError(
            f"experiment {artifact_id!r} does not exist")
    if experiment.status.value != "completed":
        raise sage_evidence.EvidenceError(
            f"experiment {artifact_id!r} status {experiment.status.value!r} is "
            f"not 'completed' — failed runs cannot support claims "
            f"({experiment.error or 'no error recorded'})")
    if program is not None:
        sage_evidence.assert_owned(program, artifact_id, plan_id=plan_id,
                                   arm=arm or "arm")

    validations = _store().experiment_validations(artifact_id)
    failed = [v["validation_type"] for v in validations
              if v["status"] == "failed"]
    if failed:
        raise sage_evidence.EvidenceError(
            f"experiment {artifact_id!r} failed known-answer validation "
            f"({', '.join(sorted(failed))}); a metric that does not reproduce "
            f"its published values cannot support a claim")

    verified = verify_geometry_bundle(artifact_id)
    return {
        "artifact": artifact_id,
        "metric": experiment.metric_name,
        "metric_hash": experiment.metric_hash,
        "parameter_values": dict(experiment.parameter_values),
        "validations": {"total": len(validations),
                        "passed": sum(1 for v in validations
                                      if v["status"] == "passed")},
        "independently_verified": all(v.get("independently_verified")
                                      for v in validations) if validations
                                  else False,
        **verified,
    }


def _arm_row(experiment_id: str) -> dict:
    """One arm's reported physics, with every measure's availability intact."""
    experiment = _store().load_experiment(experiment_id)
    if experiment is None:
        raise ValueError(f"geometry experiment {experiment_id!r} is missing")

    report = _bundle_report(experiment_id)
    validations = _store().experiment_validations(experiment_id)
    row = {
        "experiment_id": experiment_id,
        "metric": experiment.metric_name,
        "metric_hash": experiment.metric_hash,
        "parameter_values": dict(experiment.parameter_values),
        "coordinate_system": None,
        "dimension": None,
        "unit": None,
        "integrals": None,
        "chart_sensitivity": None,
        "validations_passed": sum(1 for v in validations
                                  if v["status"] == "passed"),
        "validations_failed": sum(1 for v in validations
                                  if v["status"] == "failed"),
        "energy_conditions_violated": sorted(
            v["validation_type"] for v in validations
            if v["status"] == "passed" and (
                "violation" in v["validation_type"]
                or "negative_energy" in v["validation_type"])),
    }
    if report is None:
        row["integrals_reason"] = (
            "this run sampled no grid, so no energy integral was computed; "
            "its symbolic tensors and known-answer validations still ran")
        return row

    integrals = report["integrals"]
    row["integrals"] = integrals
    row["chart_sensitivity"] = report["chart_sensitivity"]
    row["coordinate_system"] = tuple(report["spatial_axes"])
    available = [m for m in ("coordinate", "proper") if integrals[m]["available"]]
    if available:
        first = integrals[available[0]]
        row["dimension"] = first["dimension"]
        row["unit"] = first["unit"]
    return row


def _comparable(baseline: dict, candidate: dict) -> str | None:
    """Why these two arms' totals may not be subtracted, or ``None``.

    Both refusals are dimensional rather than stylistic — see this module's
    docstring and limitations 9a.
    """
    if baseline["integrals"] is None or candidate["integrals"] is None:
        return ("one of these arms sampled no grid, so there is no integral "
                "to difference")
    if baseline["dimension"] != candidate["dimension"]:
        return (f"the arms integrate over different numbers of dimensions "
                f"({baseline['dimension']} vs {candidate['dimension']}); a "
                f"slice integral and a volume integral are not the same "
                f"quantity and differencing them is wrong by a dimension")
    if baseline["coordinate_system"] != candidate["coordinate_system"]:
        return (f"the arms are sampled in different charts "
                f"({'/'.join(baseline['coordinate_system'] or ())} vs "
                f"{'/'.join(candidate['coordinate_system'] or ())}); a 2-D "
                f"total is per unit length of the suppressed direction only "
                f"when that direction's length element is the coordinate "
                f"differential, which is chart-dependent (limitations 9a). "
                f"Both arms' numbers are reported; the difference is not")
    return None


def _delta(baseline: dict, candidate: dict) -> dict:
    """Per-measure change from baseline, only where it means something."""
    out: dict = {}
    for measure in ("coordinate", "proper"):
        a = baseline["integrals"][measure]
        b = candidate["integrals"][measure]
        if not (a["available"] and b["available"]):
            out[measure] = {
                "available": False,
                "reason": a["reason"] or b["reason"] or "measure unavailable"}
            continue
        out[measure] = {
            "available": True,
            "total_change": b["total"] - a["total"],
            "negative_part_change": b["negative_part"] - a["negative_part"],
            # The ratio is what a scaling study reads; guard the zero rather
            # than emit an infinity that would serialize as invalid JSON.
            "negative_part_ratio": (b["negative_part"] / a["negative_part"]
                                    if a["negative_part"] else None),
        }
    return out


def compare(ctx, artifacts, mode="arms", tolerances=None):
    if mode == "arms":
        baseline_key = next(k for k in artifacts if k.startswith("baseline"))
        rows = {key: _arm_row(experiment_id)
                for key, experiment_id in artifacts.items()}
        baseline = rows[baseline_key]

        comparisons = {}
        for key, row in rows.items():
            if key == baseline_key:
                continue
            refusal = _comparable(baseline, row)
            comparisons[key] = (
                {"comparable": False, "reason": refusal} if refusal
                else {"comparable": True, "measures": _delta(baseline, row)})
        return {
            "baseline_arm": baseline_key,
            "arms": rows,
            "comparisons": comparisons,
            # Stated rather than implied: the analyst role reads this, and
            # the whole point of B-16 is that one number would be a lie.
            "verdict_basis": (
                "integrated energy in three measures, never aggregated; "
                "chart_sensitivity is |proper/coordinate| on the negative "
                "part and says how much of an answer is the coordinate "
                "system rather than the physics"),
        }

    rel = (tolerances or {}).get("relative", 0.0)
    absolute = (tolerances or {}).get("absolute", 0.0)
    out = {}
    for step, original_id in artifacts["original"].items():
        a = _observables(original_id)
        b = _observables(artifacts["repeat"][step])
        mismatches = []
        observables = {}
        for name in REPEAT_OBSERVABLES:
            x, y = a.get(name), b.get(name)
            observables[name] = {"original": x, "repeat": y}
            if x is None and y is None:
                continue          # not computable on both sides — agreement
            if x is None or y is None:
                mismatches.append(name)
                continue
            if not abs(x - y) <= rel * max(abs(x), abs(y)) + absolute:
                mismatches.append(name)
        if not observables:
            raise ValueError(
                f"repeat of {original_id!r} compared no observables; a "
                f"vacuous comparison is not a pass")
        out[step] = {"agrees": not mismatches, "mismatches": mismatches,
                     "observables": observables}
    return out


def _observables(experiment_id: str) -> dict:
    """The flat numbers a repeat compares, from the stored bundle."""
    report = _bundle_report(experiment_id)
    if report is None:
        return {}
    integrals = report["integrals"]
    out: dict = {"chart_sensitivity": report["chart_sensitivity"]}
    for measure in ("coordinate", "proper"):
        entry = integrals[measure]
        out[f"{measure}_total"] = entry["total"] if entry["available"] else None
        out[f"{measure}_negative_part"] = (entry["negative_part"]
                                           if entry["available"] else None)
    out["negative_fraction"] = (integrals["coordinate"]["negative_fraction"]
                                if integrals["coordinate"]["available"] else None)
    return out


def validate_arm(program, arm) -> None:
    """Design-time policy check, in geometry's vocabulary.

    Fail-early only. ``submit_geometry_experiment`` enforces the same
    allowlist authoritatively at submission, by content hash and fail-closed;
    this exists so a plan the policy forbids is refused before a human is
    asked to approve it.
    """
    from forge_metrics import builtin_metrics, load_metric_file

    payload = arm.payload
    wanted_hash = str(payload.get("metric_hash") or "").strip()
    wanted_name = str(payload.get("metric_name") or "").strip()
    if not (wanted_hash or wanted_name):
        raise ValueError(f"the {arm.kind} arm names neither metric_hash nor "
                         f"metric_name")

    definition = None
    for key, path in builtin_metrics().items():
        candidate = load_metric_file(path).definition
        if (candidate.hash == wanted_hash if wanted_hash else key == wanted_name):
            definition = candidate
            break
    if definition is None:
        raise ValueError(f"unknown metric {(wanted_hash or wanted_name)!r}")
    if definition.hash not in program.policy.allowed_metric_hashes:
        raise ValueError(
            f"metric {definition.name!r} (hash {definition.hash[:12]}) is not "
            f"allowlisted for this program")

    values = payload.get("parameter_values") or payload.get("parameters") or {}
    unknown = set(values) - set(definition.parameters)
    if unknown:
        raise ValueError(f"unknown parameters for metric {definition.name!r}: "
                         f"{sorted(unknown)}")


def claims_undomained_plan(steps) -> bool:
    """_compat_: recognise a plan stored before the platform's P-4 change.

    A geometry plan is one whose steps name a metric. Matter's twin claims
    steps naming a configuration, so exactly one of us answers for any given
    legacy plan. Delete this when no stored plan predates P-4.
    """
    return any(step.get("metric_hash") or step.get("metric_name")
               for step in steps)


PROTOCOL = ExperimentProtocol(
    domain="geometry",
    artifact_type=ARTIFACT_TYPE,
    submit=submit,
    exists=exists,
    required_tools=("submit_geometry_experiment",),
    verify=verify,
    compare=compare,
    validate_arm=validate_arm,
    claims_undomained_plan=claims_undomained_plan,
    description="Evaluate an allowlisted metric at a baseline parameter set "
                "and at candidate parameter sets, then compare what each "
                "spacetime demands: integrated energy in all three measures "
                "with its chart sensitivity, never aggregated.",
)

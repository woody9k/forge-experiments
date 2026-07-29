"""Geometry-domain SAGE tools (platform-split Phase 2).

Implementations moved verbatim from ``apps/coordinator/sage_tools.py``; the
tool *specs* moved from the static registry in ``forge_sage.tools``.  Both
are contributed to the platform through the geometry plugin declaration
(``apps/api/geometry.py``) and synced by ``apps/plugins/registry.py`` — the
core dispatch and policy layers no longer know these names exist.

Everything here still flows through ``sage_tools.call_tool``: policy
authorization, role scoping, audit rows, and the fail-closed metric
allowlist are unchanged.
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from apps.coordinator import store
import forge_geometry.app.store as gstore
from forge_geometry.app.runner import experiments_dir
from apps.coordinator.sage_tools import ToolExecutionError, _safe_id
from forge_metrics import builtin_metrics, load_metric_file
from forge_sage import Role
from forge_sage.policies import RiskClass, metric_allowed
from forge_sage.tools import read_tool, write_tool

_ALL = set(Role)


# ------------------------------------------------------------------ read impls

def _list_metrics(program, args):
    out = []
    for name, path in builtin_metrics().items():
        pm = load_metric_file(path)
        d = pm.definition
        out.append({"name": d.name, "version": d.version, "hash": d.hash,
                    "description": d.description,
                    "parameters": sorted(d.parameters),
                    "allowed": d.hash in program.policy.allowed_metric_hashes})
    return {"metrics": out}


def _get_metric(program, args):
    path = builtin_metrics().get(args["name"])
    if path is None:
        raise ToolExecutionError(f"unknown metric {args['name']!r}")
    return load_metric_file(path).definition.model_dump(mode="json")


def _get_experiment(program, args):
    exp = gstore.load_experiment(args["experiment_id"])
    if exp is None:
        raise ToolExecutionError(f"unknown experiment {args['experiment_id']!r}")
    return exp.model_dump(mode="json")


def _get_experiment_results(program, args):
    return {"experiment_id": args["experiment_id"],
            "results": gstore.experiment_results(args["experiment_id"])}


def _get_experiment_validations(program, args):
    return {"experiment_id": args["experiment_id"],
            "validations": gstore.experiment_validations(args["experiment_id"])}


def bundle_manifest(experiment_id: object) -> dict:
    """Read one experiment's bundle manifest, safely.

    Public because the MCP resource surface reads the same manifest through
    the same containment checks — one implementation, no second path.
    """

    # Defense in depth: id-shape validation *and* containment after resolving,
    # so neither a crafted id nor a symlinked bundle dir can escape the store.
    exp_id = _safe_id(experiment_id)
    root = experiments_dir().resolve()
    manifest_path = (root / exp_id / "manifest.json").resolve()
    if not manifest_path.is_relative_to(root):
        raise ToolExecutionError(f"invalid id {exp_id!r}")
    if not manifest_path.is_file():
        raise ToolExecutionError(f"no bundle manifest for experiment {exp_id!r}")
    return json.loads(manifest_path.read_text())


def _get_bundle_manifest(program, args):
    return bundle_manifest(args["experiment_id"])


def _compare_experiments(program, args):
    a, b = args["experiment_a"], args["experiment_b"]
    rows: dict[str, dict] = {}
    for label, exp_id in (("a", a), ("b", b)):
        for v in gstore.experiment_validations(exp_id):
            entry = rows.setdefault(v["validation_type"], {})
            entry[label] = {"status": v["status"], "residual": v.get("residual")}
    return {"experiment_a": a, "experiment_b": b, "validations": rows}


# ----------------------------------------------------------------- write impls

def _submit_geometry_experiment(program, args):
    """Run one geometry experiment through the existing Metric Forge pipeline.

    Same allowlist discipline as the matter path, one level stricter because
    metrics are the trusted library: the metric's *content hash* must be on
    ``policy.allowed_metric_hashes``, which fails closed — an empty allowlist
    permits nothing (``forge_sage.policies.metric_allowed``).  Execution goes
    through ``runner.execute_experiment``, the identical path
    ``POST /api/v1/experiments`` uses, so SAGE cannot bypass a single
    validation: it submits, and Warp Forge decides whether the result is valid
    (re-verified in ``sage_evidence.verify_geometry_experiment``).
    """

    from forge_geometry.app.runner import execute_experiment
    from forge_geometry.entities import (
        EnergyConditionConfig, Experiment, GridSpec, SolverBackend,
    )
    from forge_domain.entities import ExperimentStatus

    # Addressable by content hash (what the allowlist is written in, and what
    # the MCP binding sends) or by name; one of the two is required.
    wanted_hash = str(args.get("metric_hash") or "").strip()
    wanted_name = str(args.get("metric_name") or "").strip()
    if not wanted_hash and not wanted_name:
        raise ToolExecutionError(
            "submit_geometry_experiment requires metric_hash or metric_name")
    definition = name = None
    for key, path in builtin_metrics().items():
        candidate = load_metric_file(path).definition
        if (candidate.hash == wanted_hash if wanted_hash else key == wanted_name):
            # The *library key* (directory name) is what the runner resolves
            # the definition file by; never the definition's self-declared name.
            definition, name = candidate, key
            break
    if definition is None:
        raise ToolExecutionError(
            f"unknown metric {(wanted_hash or wanted_name)!r}")
    if not metric_allowed(program.policy, definition.hash):
        # Fail closed: an empty allowlist permits nothing.
        raise ToolExecutionError(
            f"metric {name!r} (hash {definition.hash[:12]}) is not allowlisted "
            f"for this program")

    values = dict(args.get("parameter_values") or args.get("parameters") or {})
    unknown = set(values) - set(definition.parameters)
    if unknown:
        raise ToolExecutionError(
            f"unknown parameters for metric {name!r}: {sorted(unknown)}")
    try:
        values = {k: float(v) for k, v in values.items()}
    except (TypeError, ValueError) as exc:
        raise ToolExecutionError(f"non-numeric parameter value: {exc}") from exc

    try:
        grid = GridSpec.model_validate(args["grid"]) if args.get("grid") else None
        conditions = (EnergyConditionConfig.model_validate(args["energy_conditions"])
                      if args.get("energy_conditions") else None)
        backend = SolverBackend(args.get("solver_backend", SolverBackend.SYMPY))
    except (ValidationError, ValueError) as exc:
        raise ToolExecutionError(f"invalid experiment specification: {exc}") from exc

    reserved = _safe_id(args["experiment_id"]) if args.get("experiment_id") else None
    experiment = Experiment(
        **({"id": reserved} if reserved else {}),
        metric_name=name,
        metric_version=definition.version,
        metric_hash=definition.hash,
        parameter_values=values,
        grid=grid,
        energy_conditions=conditions,
        solver_backend=backend,
        random_seed=int(args.get("seed", 0)),
        status=ExperimentStatus.QUEUED,
    )
    # Reserve-first is the caller's job (the id above); persisting the queued
    # spec before execution keeps the record even if the pipeline dies.
    gstore.save_experiment(experiment)
    try:
        run, _ = execute_experiment(experiment)
    except Exception as exc:  # prepare-stage failure re-raises out of the runner
        gstore.save_experiment(experiment)
        raise ToolExecutionError(
            f"geometry experiment {experiment.id} failed to start: {exc}") from exc
    gstore.save_experiment(experiment)
    gstore.save_results(run.computation_results, run.validation_results)

    # Warp Forge decides validity, not the submitter: the manifest is re-read
    # from disk and every artifact checksum re-derived before this tool reports
    # anything about the run.  The numbers below come from that re-verification.
    from apps.coordinator import sage_evidence
    try:
        verified = sage_evidence.verify_geometry_bundle(experiment.id)
    except sage_evidence.EvidenceError as exc:
        # A bundle that does not re-verify is not a result — fail loud, and
        # leave the audit row that every other tool outcome leaves.
        raise ToolExecutionError(
            f"geometry bundle for {experiment.id} failed re-verification: "
            f"{exc}") from exc
    return {
        "experiment_id": experiment.id,
        "status": experiment.status.value,
        "spec_hash": experiment.spec_hash(),
        "error": experiment.error,
        "validation_summary": verified["validation_summary"],
        "warnings": verified["warnings"],
        "bundle": experiment.id,
    }


#: (spec, handler) contributions the geometry plugin registers.
TOOLS = [
    (read_tool("list_metrics", _ALL, "List trusted metric definitions."),
     _list_metrics),
    (read_tool("get_metric", _ALL, "Fetch one metric definition by name."),
     _get_metric),
    (read_tool("get_experiment", _ALL, "Fetch an experiment record."),
     _get_experiment),
    (read_tool("get_experiment_results", _ALL,
               "Fetch validated experiment results."),
     _get_experiment_results),
    (read_tool("get_experiment_validations", _ALL,
               "Fetch experiment validations."),
     _get_experiment_validations),
    (read_tool("get_bundle_manifest", _ALL,
               "Fetch a bundle manifest + checksums."),
     _get_bundle_manifest),
    (read_tool("compare_experiments",
               {Role.ANALYST, Role.SKEPTIC, Role.PLANNER},
               "Compare two experiments' validated observables."),
     _compare_experiments),
    (write_tool("submit_geometry_experiment", RiskClass.R2_BOUNDED_EXPERIMENT,
                {Role.DESIGNER},
                "Submit an approved geometry experiment to Warp Forge."),
     _submit_geometry_experiment),
]

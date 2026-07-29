"""Geometry queue task handlers (platform-split Phase 2, decision D6).

Task bodies moved verbatim from ``apps/worker_symbolic/tasks.py`` and
``apps/worker_numerical/tasks.py``: the Celery workers are now generic task
executors, and these handlers reach them only through the plugin registry
(``registry.add_task_type`` in the geometry plugin declaration).  Wire names
and queue assignments are unchanged — this is the same queue protocol.

Symbolic worker: exact tensor algebra and known-answer validation; on
success chains the numerical phase when the experiment requests a grid.
Numerical worker: grid evaluation and energy-condition analysis,
reconstructing symbolic results from the bundle.  Trust boundary: srepr
expressions are only ever loaded from bundles this deployment's symbolic
worker wrote (checksummed in the manifest); the API never accepts raw
expressions from clients into this path.
"""

from __future__ import annotations

import json
import logging
import platform
from types import SimpleNamespace

import sympy as sp

from apps.coordinator import store
import forge_geometry.app.store as gstore
from forge_geometry.app import runner
from forge_domain.entities import ExperimentStatus, utcnow
from forge_geometry.entities import Experiment, ValidationResult
from forge_sdk.pipelines import QueueTaskType

log = logging.getLogger("forge.worker.geometry")


def symbolic_capabilities() -> dict:
    import os
    return {
        "cpu_architecture": platform.machine(),
        "cpu_count": os.cpu_count(),
        "gpu": None,
        "precisions": ["exact"],
        "backends": ["sympy"],
    }


def numerical_capabilities() -> dict:
    import os
    caps = {
        "cpu_architecture": platform.machine(),
        "cpu_count": os.cpu_count(),
        "gpu": None,
        "gpu_memory": None,
        "precisions": ["float64"],
        "backends": ["numpy"],
    }
    try:  # JAX/GPU detection is best-effort and honest about absence
        import jax  # type: ignore

        caps["backends"].append("jax")
        devs = [d for d in jax.devices() if d.platform == "gpu"]
        caps["gpu"] = devs[0].device_kind if devs else None
    except Exception:
        pass
    return caps


def run_experiment_symbolic(task, experiment_json: dict) -> dict:
    exp = Experiment.model_validate(experiment_json)
    trace = {"experiment_id": exp.id, "task_id": task.request.id,
             "worker": task.request.hostname}
    log.info("symbolic phase start", extra=trace)
    store.heartbeat_worker(task.request.hostname or "symbolic-local",
                           "symbolic", symbolic_capabilities())

    exp.started_at = utcnow()
    exp.status = ExperimentStatus.RUNNING
    gstore.save_experiment(exp)
    try:
        run = runner.prepare_run(exp)
        runner.run_symbolic_phase(run)
    except Exception as exc:
        log.error("symbolic phase failed: %s", exc, extra=trace)
        exp.status = ExperimentStatus.FAILED
        exp.error = str(exc)
        exp.completed_at = utcnow()
        gstore.save_experiment(exp)
        raise

    gstore.save_results(run.computation_results, run.validation_results)

    if exp.grid is not None:
        # hand off to the numerical queue; it re-reads everything from the bundle
        from apps.queue_app import celery_app
        gstore.save_experiment(exp)
        celery_app.send_task("forge.run_experiment_numerical",
                             args=[exp.model_dump(mode="json")])
        log.info("symbolic phase done; numerical phase queued", extra=trace)
    else:
        manifest = runner.finalize_run(run, ExperimentStatus.COMPLETED)
        gstore.save_experiment(exp)
        log.info("experiment completed (symbolic only)", extra=trace)
        return manifest
    return {"chained": True}


def _load_geometry_from_bundle(exp: Experiment, parsed):
    from apps.coordinator.bundles import experiments_dir

    bundle = experiments_dir() / exp.id
    exprs = json.loads((bundle / "expressions.json").read_text())
    n = len(parsed.coords)

    def mat(key):
        return sp.Matrix([[sp.sympify(exprs[key][i][j]) for j in range(n)]
                          for i in range(n)])

    return SimpleNamespace(
        dim=n,
        metric=mat("metric"),
        inverse_metric=mat("inverse_metric"),
        stress_energy=mat("stress_energy"),
        warnings=[],
    )


def run_experiment_numerical(task, experiment_json: dict) -> dict:
    exp = Experiment.model_validate(experiment_json)
    trace = {"experiment_id": exp.id, "task_id": task.request.id,
             "worker": task.request.hostname}
    log.info("numerical phase start", extra=trace)
    store.heartbeat_worker(task.request.hostname or "numerical-local",
                           "numerical", numerical_capabilities())

    try:
        run = runner.prepare_run(exp)
        run.geometry = _load_geometry_from_bundle(exp, run.parsed)
        validations_file = run.bundle_dir / "validations.json"
        if validations_file.exists():
            run.validation_results = [
                ValidationResult.model_validate(v)
                for v in json.loads(validations_file.read_text())
            ]
        runner.run_numerical_phase(run)
        manifest = runner.finalize_run(run, ExperimentStatus.COMPLETED)
    except Exception as exc:
        log.error("numerical phase failed: %s", exc, extra=trace)
        exp.status = ExperimentStatus.FAILED
        exp.error = str(exc)
        exp.completed_at = utcnow()
        gstore.save_experiment(exp)
        raise

    gstore.save_results(run.computation_results, [])
    exp.status = ExperimentStatus.COMPLETED
    exp.completed_at = utcnow()
    gstore.save_experiment(exp)
    log.info("experiment completed", extra=trace)
    return {"status": "completed", "warnings": manifest["warnings"]}


TASK_TYPES = [
    QueueTaskType(name="forge.run_experiment_symbolic", queue="symbolic",
                  handler=run_experiment_symbolic),
    QueueTaskType(name="forge.run_experiment_numerical", queue="numerical",
                  handler=run_experiment_numerical),
]

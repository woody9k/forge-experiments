"""Spacetime-geometry endpoints: metric library, experiments, results.

Extracted verbatim from apps/api/main.py (platform-split Phase 2, PR 1) so
the geometry domain is a mounted router like matter/fabric/sage rather than
living in the app shell.  Routes and behavior are unchanged; this file is
destined for the geometry plugin in the Forge Experiments repository.
"""

from __future__ import annotations

import json
import os

import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from apps.coordinator import store
import forge_geometry.app.store as gstore
from forge_geometry.app import runner
from forge_domain.entities import ExperimentStatus
from forge_geometry.entities import EnergyConditionConfig, Experiment, GridSpec, SolverBackend
from forge_metrics import builtin_metrics, load_metric_definition, load_metric_file
from forge_metrics.loader import MetricLoadError

router = APIRouter()

EAGER = os.environ.get("FORGE_EAGER") == "1"


# ------------------------------------------------------------------ metrics

@router.get("/api/v1/metrics")
def get_metrics() -> list[dict]:
    out = []
    for name, path in builtin_metrics().items():
        try:
            pm = load_metric_file(path)
            d = pm.definition
            out.append({
                "name": d.name, "version": d.version, "hash": d.hash,
                "description": d.description, "coordinates": d.coordinates,
                "coordinate_system": d.coordinate_system,
                "signature": d.signature, "units_mode": d.units_mode.value,
                "parameters": {k: v.model_dump() for k, v in d.parameters.items()},
                "default_grid": d.default_grid.model_dump() if d.default_grid else None,
                "source_citation": d.source_citation,
                "validation_suite_available": name in ("minkowski", "schwarzschild",
                                                       "alcubierre", "natario"),
            })
        except MetricLoadError as exc:
            out.append({"name": name, "error": str(exc)})
    return out


@router.get("/api/v1/metrics/{name}")
def get_metric(name: str) -> dict:
    path = builtin_metrics().get(name)
    if path is None:
        raise HTTPException(404, f"unknown metric {name!r}")
    pm = load_metric_file(path)
    d = pm.definition.model_dump(mode="json")
    d["parsed_components"] = {
        f"g_{i}{j}": str(pm.matrix[i, j])
        for i in range(pm.definition.dimensions)
        for j in range(i, pm.definition.dimensions)
    }
    return d


@router.post("/api/v1/metrics/validate")
def validate_metric_definition(raw: dict) -> dict:
    """Dry-run schema + parser validation of an uploaded definition.
    v0.1 does not persist uploaded metrics into the trusted library."""
    try:
        pm = load_metric_definition(raw)
    except MetricLoadError as exc:
        return {"valid": False, "error": str(exc)}
    return {"valid": True, "hash": pm.definition.hash,
            "parsed_components": {f"g_{i}{j}": str(pm.matrix[i, j])
                                  for i in range(pm.definition.dimensions)
                                  for j in range(i, pm.definition.dimensions)}}


# -------------------------------------------------------------- experiments

class ExperimentRequest(BaseModel):
    metric_name: str
    parameter_values: dict[str, float] = Field(default_factory=dict)
    grid: GridSpec | None = None
    energy_conditions: EnergyConditionConfig | None = None
    solver_backend: SolverBackend = SolverBackend.SYMPY
    random_seed: int = 0


@router.post("/api/v1/experiments", status_code=202)
def create_experiment(req: ExperimentRequest) -> dict:
    path = builtin_metrics().get(req.metric_name)
    if path is None:
        raise HTTPException(404, f"unknown metric {req.metric_name!r}")
    pm = load_metric_file(path)
    unknown = set(req.parameter_values) - set(pm.definition.parameters)
    if unknown:
        raise HTTPException(422, f"unknown parameters: {sorted(unknown)}")

    exp = Experiment(
        metric_name=req.metric_name,
        metric_version=pm.definition.version,
        metric_hash=pm.definition.hash,
        parameter_values=req.parameter_values,
        grid=req.grid,
        energy_conditions=req.energy_conditions,
        solver_backend=req.solver_backend,
        random_seed=req.random_seed,
        status=ExperimentStatus.QUEUED,
    )
    gstore.save_experiment(exp)

    if EAGER:
        run, manifest = runner.execute_experiment(exp)
        gstore.save_experiment(exp)
        gstore.save_results(run.computation_results, run.validation_results)
    else:
        from apps.queue_app import celery_app
        celery_app.send_task("forge.run_experiment_symbolic",
                             args=[exp.model_dump(mode="json")])
    return {"id": exp.id, "status": exp.status.value, "spec_hash": exp.spec_hash()}


@router.get("/api/v1/experiments")
def get_experiments(limit: int = 100) -> list[dict]:
    return gstore.list_experiments(limit=min(limit, 500))


@router.get("/api/v1/experiments/{experiment_id}")
def get_experiment(experiment_id: str) -> dict:
    exp = gstore.load_experiment(experiment_id)
    if exp is None:
        raise HTTPException(404, "experiment not found")
    return exp.model_dump(mode="json")


@router.post("/api/v1/experiments/{experiment_id}/cancel")
def cancel_experiment(experiment_id: str) -> dict:
    exp = gstore.load_experiment(experiment_id)
    if exp is None:
        raise HTTPException(404, "experiment not found")
    if exp.status in (ExperimentStatus.COMPLETED, ExperimentStatus.FAILED):
        raise HTTPException(409, f"experiment already {exp.status.value}")
    gstore.update_status(experiment_id, ExperimentStatus.CANCELLED)
    return {"id": experiment_id, "status": "cancelled",
            "note": "queued task will be skipped; running tasks stop at next phase boundary"}


@router.post("/api/v1/experiments/{experiment_id}/rerun", status_code=202)
def rerun_experiment(experiment_id: str) -> dict:
    old = gstore.load_experiment(experiment_id)
    if old is None:
        raise HTTPException(404, "experiment not found")
    new = Experiment(**{**old.model_dump(exclude={"id", "status", "created_at",
                                                  "started_at", "completed_at", "error"})})
    new.status = ExperimentStatus.QUEUED
    gstore.save_experiment(new)
    if EAGER:
        run, _ = runner.execute_experiment(new)
        gstore.save_experiment(new)
        gstore.save_results(run.computation_results, run.validation_results)
    else:
        from apps.queue_app import celery_app
        celery_app.send_task("forge.run_experiment_symbolic",
                             args=[new.model_dump(mode="json")])
    return {"id": new.id, "rerun_of": experiment_id,
            "same_spec": new.spec_hash() == old.spec_hash()}


# ------------------------------------------------------------------ results

@router.get("/api/v1/experiments/{experiment_id}/results")
def get_results(experiment_id: str) -> list[dict]:
    return gstore.experiment_results(experiment_id)


@router.get("/api/v1/experiments/{experiment_id}/validations")
def get_validations(experiment_id: str) -> list[dict]:
    return gstore.experiment_validations(experiment_id)


@router.get("/api/v1/experiments/{experiment_id}/visualizations")
def get_visualizations(experiment_id: str) -> dict:
    """Heatmap-ready data: 2-D energy-density slice with axes and metadata."""
    bundle = runner.experiments_dir() / experiment_id
    manifest_path = bundle / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(404, "no results bundle for this experiment")
    manifest = json.loads(manifest_path.read_text())
    out = {"experiment": manifest["experiment"], "warnings": manifest["warnings"],
           "fields": {}, "energy_conditions": None}
    ec_path = bundle / "energy_conditions.json"
    if ec_path.exists():
        out["energy_conditions"] = json.loads(ec_path.read_text())
    ed = bundle / "arrays" / "energy_density.npz"
    grid = bundle / "arrays" / "grid.npz"
    if ed.exists() and grid.exists():
        with np.load(ed) as z, np.load(grid) as gz:
            rho = z["eulerian_energy_density"]
            axes = {k.removeprefix("axis_"): gz[k].tolist()
                    for k in gz.files if k.startswith("axis_")}
        if rho.ndim == 2:
            out["fields"]["eulerian_energy_density"] = {
                "values": np.where(np.isfinite(rho), rho, None).tolist(),
                "axes": axes,
                "units": "geometrized energy density (G=c=1)",
                "solver_backend": manifest["experiment"]["solver_backend"],
                "parameter_values": manifest["experiment"]["parameter_values"],
                "resolution": list(rho.shape),
            }
    return out


@router.get("/api/v1/experiments/{experiment_id}/export")
def export_experiment(experiment_id: str) -> FileResponse:
    try:
        zip_path = runner.export_bundle_zip(experiment_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return FileResponse(zip_path, filename=zip_path.name, media_type="application/zip")

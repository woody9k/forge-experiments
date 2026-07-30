"""HTTP surface: /api/v1/pendulum/*.

A plugin's router is an ordinary FastAPI router.  It is mounted by the
platform only while this plugin is active, so these paths appear and
disappear with the plugin.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from forge_pendulum.app import runner, store
from forge_pendulum.model import small_angle_period_s

router = APIRouter(prefix="/api/v1/pendulum", tags=["pendulum"])

EAGER = os.environ.get("FORGE_EAGER") == "1"


class RunRequest(BaseModel):
    length_m: float = Field(1.0, gt=0)
    initial_angle_deg: float = 5.0
    damping: float = Field(0.0, ge=0)
    duration_s: float = Field(20.0, gt=0)
    timestep_s: float = Field(1e-3, gt=0, le=0.05)


@router.get("/predict")
def predict(length_m: float) -> dict:
    """The closed form, with no experiment: T = 2π√(L/g)."""
    if length_m <= 0:
        raise HTTPException(422, "length_m must be positive")
    return {"length_m": length_m,
            "small_angle_period_s": small_angle_period_s(length_m),
            "quality": "exact_analytic"}


@router.post("/runs", status_code=202)
def create_run(req: RunRequest) -> dict:
    spec = req.model_dump()
    if EAGER:
        run = runner.execute(spec)
        return {"id": run["id"], "status": run["status"]}
    from apps.queue_app import celery_app

    run_id = store.new_run_id()
    store.save_run({"id": run_id, "spec": spec, "status": "queued",
                    "result": None, "error": None})
    celery_app.send_task("pendulum.run_experiment", args=[spec, run_id])
    return {"id": run_id, "status": "queued"}


@router.get("/runs")
def list_runs(limit: int = 50) -> list[dict]:
    return store.list_runs(limit=min(limit, 200))


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    run = store.load_run(run_id)
    if run is None:
        raise HTTPException(404, f"unknown pendulum run {run_id!r}")
    return run

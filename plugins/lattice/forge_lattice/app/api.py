from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from forge_lattice.model import LatticeInputError, simulate_stack

router = APIRouter(prefix="/api/v1/lattice", tags=["lattice"])


class StackRequest(BaseModel):
    layer_count: int = Field(10, ge=2, le=1000)
    layer_thickness_m: float = Field(1e-6, gt=0, le=0.1)
    frequency_hz: float = Field(1e6, gt=0, le=1e12)
    dc_field_v_m: float = Field(1e4, ge=0)
    rf_field_amplitude_v_m: float = Field(1e4, ge=0)
    area_m2: float = Field(1e-4, gt=0)
    observation_distance_m: float = Field(1.0, gt=0)
    materials: dict[str, dict[str, float]] | None = None


@router.get("/experiments")
def experiments() -> list[dict[str, str]]:
    return [{"id": "mg-zn-bi-layered-field-response",
             "name": "Layered Mg-Zn/Bi field response",
             "model": "1d-planar-quasistatic-v1"}]


@router.post("/simulate")
def simulate(req: StackRequest) -> dict[str, Any]:
    try:
        return simulate_stack(req.model_dump())
    except LatticeInputError as exc:
        raise HTTPException(422, str(exc)) from exc

"""Versioned mutation operator registry.

Each operator takes (genome, params, rng) and returns (new_genome, record).
Operators are pure: same genome + params + seed ⇒ same child (tested).
Children carry parent ids, incremented generation, and the full mutation
history. Hard campaign constraints are never touched by operators — they
mutate physics parameters only.
"""

from __future__ import annotations

import copy
from typing import Any, Callable

import numpy as np

from forge_matter.entities import MatterConfiguration, MutationRecord

OPERATOR_VERSION = "0.1.0"


class MutationError(ValueError):
    pass


def _find(items: list[dict], target_id: str, kind: str) -> dict:
    for item in items:
        if item["id"] == target_id:
            return item
    raise MutationError(f"no {kind} with id {target_id!r}")


def _scale(value: float, params: dict, rng: np.random.Generator,
           lo: float | None = None, hi: float | None = None) -> float:
    """New value: explicit `value`, or multiplicative `factor`, or a seeded
    log-uniform perturbation within ±`spread` (default 0.2)."""
    if "value" in params:
        new = float(params["value"])
    elif "factor" in params:
        new = value * float(params["factor"])
    else:
        spread = float(params.get("spread", 0.2))
        new = value * float(np.exp(rng.uniform(-spread, spread)))
    if lo is not None and new < lo:
        raise MutationError(f"mutated value {new:.4g} below bound {lo:.4g}")
    if hi is not None and new > hi:
        raise MutationError(f"mutated value {new:.4g} above bound {hi:.4g}")
    return new


def alter_separation(genome: dict, params: dict, rng: np.random.Generator):
    qb = _find(genome.get("quantum_boundaries", []), params["target"], "quantum boundary")
    before = qb["separation_m"]
    qb["separation_m"] = _scale(before, params, rng, lo=1e-10, hi=1.0)
    return {"separation_m": before}, {"separation_m": qb["separation_m"]}, [qb["id"]]


def alter_plate_area(genome: dict, params: dict, rng: np.random.Generator):
    qb = _find(genome.get("quantum_boundaries", []), params["target"], "quantum boundary")
    before = qb["plate_area_m2"]
    qb["plate_area_m2"] = _scale(before, params, rng, lo=1e-12, hi=1000.0)
    return {"plate_area_m2": before}, {"plate_area_m2": qb["plate_area_m2"]}, [qb["id"]]


def alter_plate_count(genome: dict, params: dict, rng: np.random.Generator):
    qb = _find(genome.get("quantum_boundaries", []), params["target"], "quantum boundary")
    before = qb["plate_count"]
    delta = int(params.get("delta", int(rng.integers(-2, 3)) or 1))
    new = before + delta
    if new < 2:
        raise MutationError(f"plate_count {new} < 2")
    qb["plate_count"] = new
    return {"plate_count": before}, {"plate_count": new}, [qb["id"]]


def alter_angular_velocity(genome: dict, params: dict, rng: np.random.Generator):
    comp = _find(genome.get("components", []), params["target"], "component")
    motion = comp.get("motion")
    if not motion or motion.get("type") != "rotation":
        raise MutationError(f"component {comp['id']} is not rotating")
    before = motion["angular_velocity_rad_s"]
    sign = 1.0 if before >= 0 else -1.0
    new_mag = _scale(abs(before), params, rng, lo=0.0)
    motion["angular_velocity_rad_s"] = sign * new_mag
    return ({"angular_velocity_rad_s": before},
            {"angular_velocity_rad_s": motion["angular_velocity_rad_s"]}, [comp["id"]])


def reverse_rotation(genome: dict, params: dict, rng: np.random.Generator):
    comp = _find(genome.get("components", []), params["target"], "component")
    motion = comp.get("motion")
    if not motion or motion.get("type") != "rotation":
        raise MutationError(f"component {comp['id']} is not rotating")
    before = motion["angular_velocity_rad_s"]
    motion["angular_velocity_rad_s"] = -before
    return ({"angular_velocity_rad_s": before},
            {"angular_velocity_rad_s": -before}, [comp["id"]])


def change_density(genome: dict, params: dict, rng: np.random.Generator):
    comp = _find(genome.get("components", []), params["target"], "component")
    mat = comp["material"]
    if mat["model"] != "homogeneous" or "density_kg_m3" not in mat:
        raise MutationError(
            f"component {comp['id']}: change_density supports explicit "
            "homogeneous densities only")
    before = mat["density_kg_m3"]
    mat["density_kg_m3"] = _scale(before, params, rng, lo=1.0)
    mat.pop("material_id", None)  # explicit density no longer tied to a material
    return {"density_kg_m3": before}, {"density_kg_m3": mat["density_kg_m3"]}, [comp["id"]]


OPERATORS: dict[str, Callable] = {
    "alter_separation": alter_separation,
    "alter_plate_area": alter_plate_area,
    "alter_plate_count": alter_plate_count,
    "alter_angular_velocity": alter_angular_velocity,
    "reverse_rotation": reverse_rotation,
    "change_density": change_density,
}


def mutate(parent: MatterConfiguration, operator: str, params: dict[str, Any],
           seed: int, reason: str = "") -> MatterConfiguration:
    if operator not in OPERATORS:
        raise MutationError(
            f"unknown operator {operator!r}; available: {sorted(OPERATORS)}")
    rng = np.random.default_rng(seed)
    genome = copy.deepcopy(parent.genome)
    before, after, affected = OPERATORS[operator](genome, params, rng)

    record = MutationRecord(
        operator=operator, operator_version=OPERATOR_VERSION,
        parameters_before=before, parameters_after=after,
        reason=reason or f"operator {operator} applied with params {params}",
        seed=seed, affected_components=affected,
    )
    child = MatterConfiguration(
        name=parent.name, version=parent.version,
        description=parent.description, genome=genome,
        parent_ids=[parent.id], generation=parent.generation + 1,
        mutation_history=[*parent.mutation_history, record],
    )
    if child.genome_hash == parent.genome_hash:
        raise MutationError("mutation produced an identical genome")
    return child

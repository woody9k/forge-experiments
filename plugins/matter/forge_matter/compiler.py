"""Genome → phenotype compiler.

Deterministic expansion of a schema-validated configuration into the
apparatus model the solver funnel consumes: per-component volume, mass,
moment of inertia, angular momentum, rim speed, and stress estimates; gap
regions for plate arrays; observation regions.

Contract: same genome + same COMPILER_VERSION ⇒ byte-identical phenotype
JSON (and therefore identical phenotype hash). Every approximation the
compiler makes is written into the phenotype's `approximations` list.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import jsonschema
import numpy as np
import sympy as sp
import yaml

from forge_domain.entities import content_hash
from forge_matter import materials
from forge_matter.entities import MatterConfiguration
from forge_sdk.expressions import RestrictedParseError, parse_expression

COMPILER_VERSION = "0.1.0"
C_LIGHT = 299_792_458.0
_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "matter-configuration.schema.json"
_PROFILE_SAMPLES = 512  # deterministic sample count for graded densities


class CompileError(ValueError):
    pass


def _schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text())


def load_configuration(raw: dict | str | Path, **kwargs: Any) -> MatterConfiguration:
    """Validate a raw genome dict (or YAML file path) into a configuration."""
    if isinstance(raw, (str, Path)):
        p = Path(raw)
        if p.stat().st_size > 1_000_000:
            raise CompileError("configuration file exceeds 1 MB limit")
        raw = yaml.safe_load(p.read_text())
    try:
        jsonschema.validate(raw, _schema())
    except jsonschema.ValidationError as exc:
        raise CompileError(f"configuration failed schema validation: {exc.message}") from exc

    ids = [c["id"] for c in raw.get("components", [])] + \
          [q["id"] for q in raw.get("quantum_boundaries", [])] + \
          [o["id"] for o in raw.get("observation_regions", [])]
    if len(ids) != len(set(ids)):
        raise CompileError("duplicate component/boundary/region ids")
    if raw.get("electromagnetic_systems"):
        raise CompileError(
            "electromagnetic systems are schema-reserved but unsupported by "
            "compiler v0.1.0 (Milestone 3); remove them or wait for the EM path")

    return MatterConfiguration(
        name=raw["name"], version=raw["version"],
        description=raw.get("description", ""), genome=raw, **kwargs,
    )


# ------------------------------------------------------------------ shapes

def _shape_geometry(shape: dict) -> dict:
    """Volume [m³], characteristic outer radius [m], and moment-of-inertia
    coefficient k such that I = k·M·R² about the rotation axis (z)."""
    t = shape["type"]
    if t == "sphere":
        r = _req(shape, "radius_m")
        return {"volume": 4 / 3 * math.pi * r**3, "outer_radius": r,
                "inertia_coeff": 2 / 5, "inertia_radius": r,
                "note": "solid sphere, I = 2/5 M R^2"}
    if t == "spherical_shell":
        ro = _req(shape, "outer_radius_m")
        th = _req(shape, "thickness_m")
        if th >= ro:
            raise CompileError("spherical_shell thickness must be < outer radius")
        ri = ro - th
        vol = 4 / 3 * math.pi * (ro**3 - ri**3)
        # exact thick-shell coefficient: I = 2/5 M (ro^5-ri^5)/(ro^3-ri^3)
        k = (2 / 5) * (ro**5 - ri**5) / ((ro**3 - ri**3) * ro**2)
        return {"volume": vol, "outer_radius": ro, "inertia_coeff": k,
                "inertia_radius": ro, "inner_radius": ri,
                "note": "thick spherical shell, exact I"}
    if t == "torus":
        R = _req(shape, "major_radius_m")
        r = _req(shape, "minor_radius_m")
        if r >= R:
            raise CompileError("torus minor radius must be < major radius")
        vol = 2 * math.pi**2 * R * r**2
        # I_z = M (R^2 + 3/4 r^2) for a solid torus about its symmetry axis
        k = (R**2 + 0.75 * r**2) / (R + r) ** 2
        return {"volume": vol, "outer_radius": R + r, "inertia_coeff": k,
                "inertia_radius": R + r,
                "note": "solid torus, I = M(R^2 + 3/4 r^2)"}
    if t == "cylinder":
        r = _req(shape, "radius_m")
        length = _req(shape, "length_m")
        return {"volume": math.pi * r**2 * length, "outer_radius": r,
                "inertia_coeff": 1 / 2, "inertia_radius": r,
                "note": "solid cylinder about its axis, I = 1/2 M R^2"}
    if t == "box":
        sx, sy, sz = _req(shape, "size_m")
        if min(sx, sy, sz) <= 0:
            raise CompileError("box dimensions must be positive")
        rout = math.hypot(sx, sy) / 2
        k = (sx**2 + sy**2) / (12 * rout**2)
        return {"volume": sx * sy * sz, "outer_radius": rout,
                "inertia_coeff": k, "inertia_radius": rout,
                "note": "box about z through center, I = M(sx^2+sy^2)/12"}
    raise CompileError(f"unsupported shape type {t!r}")


def _req(d: dict, key: str) -> Any:
    if key not in d:
        raise CompileError(f"shape {d.get('type')!r} requires {key!r}")
    return d[key]


# ---------------------------------------------------------------- material

def _mean_density(material: dict, approximations: list[str]) -> tuple[float, str]:
    model = material["model"]
    if model == "homogeneous":
        if "density_kg_m3" in material:
            rho = float(material["density_kg_m3"])
            src = "explicit"
            mat_id = material.get("material_id")
            if mat_id:
                db = materials.density(mat_id)
                if abs(rho - db) / db > 0.05:
                    raise CompileError(
                        f"declared density {rho} kg/m^3 deviates >5% from "
                        f"material database value {db} for {mat_id!r}")
        elif "material_id" in material:
            rho = materials.density(material["material_id"])
            src = f"material_database:{materials.database_version()}"
        else:
            raise CompileError("homogeneous material needs density_kg_m3 or material_id")
        return rho, src

    if model == "graded":
        base = material.get("base_material_id")
        if not base:
            raise CompileError("graded material requires base_material_id")
        rho0 = materials.density(base)
        profile = material.get("density_profile")
        if not profile:
            raise CompileError("graded material requires density_profile expression")
        params = {k: float(v) for k, v in material.get("profile_parameters", {}).items()}
        symbols = {"r_normalized": sp.Symbol("r_normalized", real=True),
                   "rho0": sp.Symbol("rho0", real=True),
                   **{k: sp.Symbol(k, real=True) for k in params}}
        try:
            expr = parse_expression(profile, symbols)
        except RestrictedParseError as exc:
            raise CompileError(f"invalid density profile: {exc}") from exc
        fn = sp.lambdify(
            [symbols["r_normalized"]],
            expr.subs({symbols["rho0"]: rho0,
                       **{symbols[k]: v for k, v in params.items()}}),
            modules=["numpy"])
        # deterministic radial sampling; volume-weighted mean over a ball
        r = np.linspace(0.0, 1.0, _PROFILE_SAMPLES)
        rho_r = np.broadcast_to(np.asarray(fn(r), dtype=np.float64), r.shape)
        if not np.all(np.isfinite(rho_r)):
            raise CompileError("density profile evaluates to non-finite values")
        if np.any(rho_r <= 0):
            raise CompileError(
                "density profile is non-positive somewhere in [0,1]; negative "
                "rest-mass density requires research_mode_negative_density "
                "(not supported by compiler v0.1.0)")
        mean = float(np.trapezoid(rho_r * r**2, r) / np.trapezoid(r**2, r))
        approximations.append(
            f"graded density integrated numerically as volume-weighted radial "
            f"mean over {_PROFILE_SAMPLES} samples (spherically symmetric "
            f"weighting approximation)")
        return mean, f"graded:{base}"

    raise CompileError(f"unsupported material model {model!r}")


# ---------------------------------------------------------------- compile

def compile_configuration(config: MatterConfiguration) -> dict:
    """Expand the genome into the phenotype dict and return it.
    Raises CompileError on anything unsupported — never guesses."""
    genome = config.genome
    approximations: list[str] = []
    warnings: list[str] = []
    components = []

    for comp in genome.get("components", []):
        geom = _shape_geometry(comp["shape"])
        rho, rho_src = _mean_density(comp["material"], approximations)
        mass = rho * geom["volume"]
        entry: dict[str, Any] = {
            "id": comp["id"],
            "shape_type": comp["shape"]["type"],
            "shape": comp["shape"],
            "position": comp.get("position", [0.0, 0.0, 0.0]),
            "volume_m3": geom["volume"],
            "mean_density_kg_m3": rho,
            "density_source": rho_src,
            "mass_kg": mass,
            "rest_energy_j": mass * C_LIGHT**2,
            "inertia_note": geom["note"],
        }
        motion = comp.get("motion", {"type": "none"})
        if motion["type"] == "rotation":
            omega = float(motion.get("angular_velocity_rad_s", 0.0))
            axis = motion.get("axis", [0, 0, 1])
            if list(axis) != [0, 0, 1] and list(axis) != [0, 0, -1]:
                raise CompileError(
                    f"component {comp['id']}: compiler v0.1.0 supports rotation "
                    "about the z axis only ([0,0,±1])")
            if list(axis) == [0, 0, -1]:
                omega = -omega
            I = geom["inertia_coeff"] * mass * geom["inertia_radius"] ** 2
            rim_speed = abs(omega) * geom["outer_radius"]
            if rim_speed >= C_LIGHT:
                raise CompileError(
                    f"component {comp['id']}: rim speed {rim_speed:.3e} m/s "
                    f"≥ c — superluminal material motion is rejected")
            if rim_speed > 0.01 * C_LIGHT:
                warnings.append(
                    f"{comp['id']}: rim speed {rim_speed/C_LIGHT:.4f}c — rigid-"
                    "body approximation is physically questionable above 0.01c")
            entry.update({
                "motion": "rotation",
                "angular_velocity_rad_s": omega,
                "moment_of_inertia_kg_m2": I,
                "angular_momentum_kg_m2_s": I * omega,  # z component
                "rim_speed_m_s": rim_speed,
                "rotational_energy_j": 0.5 * I * omega**2,
                "hoop_stress_pa": rho * omega**2 * geom["outer_radius"] ** 2,
                "hoop_stress_note": "thin-ring approximation sigma = rho w^2 R^2",
            })
            approximations.append(
                f"{comp['id']}: hoop stress via thin-ring approximation")
        else:
            entry.update({"motion": "none", "angular_momentum_kg_m2_s": 0.0,
                          "rotational_energy_j": 0.0, "hoop_stress_pa": 0.0})

        ms = comp.get("mechanical_state", {})
        entry["safety_factor_required"] = float(ms.get("safety_factor", 2.0))
        mat_id = comp["material"].get("material_id") or comp["material"].get("base_material_id")
        entry["material_id"] = mat_id
        if mat_id:
            entry["tensile_strength_pa"] = materials.tensile_strength(mat_id)
        components.append(entry)

    plate_systems = []
    for qb in genome.get("quantum_boundaries", []):
        n = int(qb["plate_count"])
        area = float(qb["plate_area_m2"])
        sep = float(qb["separation_m"])
        thick = float(qb.get("plate_thickness_m", 1e-4))
        mat_id = qb.get("plate_material_id", "gold")
        rho = materials.density(mat_id)
        plate_mass = rho * area * thick
        plate_systems.append({
            "id": qb["id"],
            "type": qb["type"],
            "plate_count": n,
            "gap_count": n - 1,
            "plate_area_m2": area,
            "separation_m": sep,
            "plate_thickness_m": thick,
            "plate_material_id": mat_id,
            "material_model": qb.get("material_model", "ideal_conductor"),
            "temperature_k": float(qb.get("temperature_k", 0.0)),
            "plate_mass_kg": plate_mass,
            "total_plate_mass_kg": plate_mass * n,
            "total_rest_energy_j": plate_mass * n * C_LIGHT**2,
            "gap_volume_m3": area * sep * (n - 1),
            "placement": qb.get("placement", {"topology": "single_stack"}),
        })

    regions = []
    for obs in genome.get("observation_regions", []):
        pos = obs.get("position") or obs.get("center")
        if pos is None:
            raise CompileError(f"observation region {obs['id']} needs position/center")
        regions.append({"id": obs["id"], "type": obs["type"],
                        "position": [float(x) for x in pos],
                        "radius_m": float(obs.get("radius_m", 0.0))})

    phenotype = {
        "compiler_version": COMPILER_VERSION,
        "material_db_version": materials.database_version(),
        "components": components,
        "plate_systems": plate_systems,
        "observation_regions": regions,
        "totals": {
            "mass_kg": sum(c["mass_kg"] for c in components)
            + sum(p["total_plate_mass_kg"] for p in plate_systems),
            "rest_energy_j": sum(c["rest_energy_j"] for c in components)
            + sum(p["total_rest_energy_j"] for p in plate_systems),
            "angular_momentum_z_kg_m2_s": sum(
                c["angular_momentum_kg_m2_s"] for c in components),
            "rotational_energy_j": sum(c["rotational_energy_j"] for c in components),
        },
        "approximations": approximations,
        "warnings": warnings,
        "constraints": genome.get("constraints", {}),
    }
    phenotype["phenotype_hash"] = content_hash(
        {k: v for k, v in phenotype.items() if k != "phenotype_hash"})
    config.compiler_version = COMPILER_VERSION
    config.phenotype_hash = phenotype["phenotype_hash"]
    return phenotype

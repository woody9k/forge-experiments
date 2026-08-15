"""One-dimensional, quasistatic electromagnetic model for layered stacks.

This is an engineering estimate, not a full-wave or general-relativistic
solver. The applied field is normal to infinite planar layers.
"""

from __future__ import annotations

import cmath
import math
from typing import Any

EPSILON_0 = 8.854_187_8128e-12
C = 299_792_458.0
G = 6.674_30e-11

DEFAULT_MATERIALS = {
    "mg_zn": {"relative_permittivity": 1.0, "conductivity_s_m": 1.0e7,
              "density_kg_m3": 3500.0},
    "bi": {"relative_permittivity": 1.0, "conductivity_s_m": 7.7e5,
           "density_kg_m3": 9780.0},
}


class LatticeInputError(ValueError):
    pass


def _finite(name: str, value: Any, *, positive: bool = False,
            nonnegative: bool = False) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise LatticeInputError(f"{name} must be numeric") from exc
    if not math.isfinite(out):
        raise LatticeInputError(f"{name} must be finite")
    if positive and out <= 0:
        raise LatticeInputError(f"{name} must be positive")
    if nonnegative and out < 0:
        raise LatticeInputError(f"{name} must be non-negative")
    return out


def _materials(overrides: dict | None) -> dict[str, dict[str, float]]:
    values = {k: dict(v) for k, v in DEFAULT_MATERIALS.items()}
    for name, supplied in (overrides or {}).items():
        if name not in values or not isinstance(supplied, dict):
            raise LatticeInputError(f"unsupported material {name!r}")
        values[name].update(supplied)
    for name, material in values.items():
        material["relative_permittivity"] = _finite(
            f"{name}.relative_permittivity", material["relative_permittivity"], positive=True)
        material["conductivity_s_m"] = _finite(
            f"{name}.conductivity_s_m", material["conductivity_s_m"], nonnegative=True)
        material["density_kg_m3"] = _finite(
            f"{name}.density_kg_m3", material["density_kg_m3"], positive=True)
    return values


def simulate_stack(spec: dict[str, Any]) -> dict[str, Any]:
    """Return JSON-safe field and scale estimates for an alternating stack."""
    raw_count = spec.get("layer_count", 10)
    try:
        count = int(raw_count)
    except (TypeError, ValueError) as exc:
        raise LatticeInputError("layer_count must be an integer") from exc
    if isinstance(raw_count, bool) or count != float(raw_count):
        raise LatticeInputError("layer_count must be an integer")
    if not 2 <= count <= 1000:
        raise LatticeInputError("layer_count must be between 2 and 1000")
    thickness = _finite("layer_thickness_m", spec.get("layer_thickness_m", 1e-6), positive=True)
    if thickness > 0.1:
        raise LatticeInputError("layer_thickness_m must not exceed 0.1 m")
    frequency = _finite("frequency_hz", spec.get("frequency_hz", 1e6), positive=True)
    if frequency > 1e12:
        raise LatticeInputError("frequency_hz must not exceed 1 THz")
    dc_applied = _finite("dc_field_v_m", spec.get("dc_field_v_m", 1e4), nonnegative=True)
    rf_applied = _finite("rf_field_amplitude_v_m", spec.get("rf_field_amplitude_v_m", 1e4), nonnegative=True)
    area = _finite("area_m2", spec.get("area_m2", 1e-4), positive=True)
    distance = _finite("observation_distance_m", spec.get("observation_distance_m", 1.0), positive=True)
    materials = _materials(spec.get("materials"))
    sequence = ["mg_zn" if i % 2 == 0 else "bi" for i in range(count)]
    omega = 2 * math.pi * frequency

    dc_weights = [1 / max(materials[n]["conductivity_s_m"], 1e-30) for n in sequence]
    dc_scale = dc_applied * count / sum(dc_weights)
    dc_fields = [dc_scale * w for w in dc_weights]
    gammas = [complex(materials[n]["conductivity_s_m"],
                      omega * EPSILON_0 * materials[n]["relative_permittivity"])
              for n in sequence]
    rf_weights = [1 / g for g in gammas]
    rf_scale = rf_applied * count / sum(rf_weights)
    rf_fields = [rf_scale * w for w in rf_weights]

    layers, pressures = [], []
    total_energy = total_mass = 0.0
    for i, (name, e_dc, e_rf) in enumerate(zip(sequence, dc_fields, rf_fields)):
        material = materials[name]
        epsilon = EPSILON_0 * material["relative_permittivity"]
        energy_density = 0.5 * epsilon * e_dc**2 + 0.25 * epsilon * abs(e_rf)**2
        pressure = energy_density
        total_energy += energy_density * area * thickness
        total_mass += material["density_kg_m3"] * area * thickness
        pressures.append(pressure)
        layers.append({
            "index": i, "material": name,
            "z_start_m": i * thickness, "z_end_m": (i + 1) * thickness,
            "dc_field_v_m": e_dc, "rf_field_amplitude_v_m": abs(e_rf),
            "rf_phase_rad": cmath.phase(e_rf),
            "em_energy_density_j_m3": energy_density,
            "maxwell_pressure_pa": pressure,
        })
    interfaces = [{
        "between_layers": [i, i + 1],
        "pressure_difference_pa": pressures[i + 1] - pressures[i],
        "force_estimate_n": (pressures[i + 1] - pressures[i]) * area,
    } for i in range(count - 1)]
    eps_eff = count / sum(1 / materials[n]["relative_permittivity"] for n in sequence)
    sigma_eff = count / sum(1 / max(materials[n]["conductivity_s_m"], 1e-30) for n in sequence)
    gamma_eff = count / sum(1 / g for g in gammas)
    em_mass = total_energy / C**2
    return {
        "model": "1d-planar-quasistatic-v1",
        "inputs": {"layer_count": count, "layer_thickness_m": thickness,
                   "frequency_hz": frequency, "dc_field_v_m": dc_applied,
                   "rf_field_amplitude_v_m": rf_applied, "area_m2": area,
                   "materials": materials},
        "layers": layers, "interfaces": interfaces,
        "effective_properties": {
            "relative_permittivity_normal": eps_eff,
            "dc_conductivity_normal_s_m": sigma_eff,
            "rf_complex_admittivity_s_m": {"real": gamma_eff.real, "imag": gamma_eff.imag},
            "bulk_density_kg_m3": total_mass / (area * count * thickness),
        },
        "totals": {"stack_thickness_m": count * thickness, "em_energy_j": total_energy,
                   "em_mass_equivalent_kg": em_mass,
                   "weak_field_acceleration_scale_m_s2": G * em_mass / distance**2,
                   "max_abs_interface_force_n": max(abs(x["force_estimate_n"]) for x in interfaces)},
        "interpretation": {
            "conventional": "Field division, dielectric energy and Maxwell-pressure estimates are conventional quasistatic electromagnetism within the stated 1D assumptions.",
            "gravity": "The gravity value is only a dimensional weak-field scale obtained from E/c^2 and Newtonian gravity; it is not a prediction of anomalous gravity, propulsion, metric engineering, or measurable spacetime curvature.",
            "limitations": ["infinite planar layers; no edge or electrode geometry",
                            "no full-wave resonances, skin-depth solution, magnetic field, heating, breakdown, electrostriction, or structural mechanics",
                            "material defaults are representative placeholders and must be replaced with measured, frequency- and temperature-dependent sample data"],
        },
    }

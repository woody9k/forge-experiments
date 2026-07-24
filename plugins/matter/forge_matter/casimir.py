"""Quantum-vacuum module: Casimir analysis.

v0.2.0 implements exactly one model — ideal parallel conducting plates at
zero temperature (Brown & Maclay 1969; Casimir 1948):

    E/A  = −π²ħc / (720 a³)          energy per unit plate area, per gap
    F/A  = −π²ħc / (240 a⁴)          force per unit area (attractive)
    u    = −π²ħc / (720 a⁴)          energy density in the gap
    ⟨T^μ_ν⟩ = (π²ħc / 720 a⁴) · diag(−1, 1, 1, −3)   (z normal to plates)

Everything else (finite conductivity, finite temperature, cavities,
roughness, dynamic boundaries, …) is a registered extension that returns
`model_unavailable`. Numbers are never produced by hand-waving an
unsupported geometry.

Semantics contract: results always embed the five-part energy account and
the fixed negative-energy warning — a locally negative renormalized vacuum
energy density is not free-standing negative-energy fuel.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from forge_matter.entities import ConfidenceLevel, EnergyAccount, StressEnergyContribution

MODULE_VERSION = "0.1.0"
HBAR = 1.054_571_817e-34   # J s (CODATA 2018, exact-derived)
C_LIGHT = 299_792_458.0    # m/s (exact)
G_SI = 6.674_30e-11

# Validity thresholds for the ideal-conductor T=0 model (design doc §4)
ROUGHNESS_LIMIT_M = 1e-8      # below: roughness/plasma-wavelength dominated
CONDUCTIVITY_NOTE_LIMIT_M = 1e-6
THERMAL_NOTE_TEMPERATURE_K = 0.5

#: Registered models. Only ideal_parallel_plates is computable in v0.2.0.
MODELS = {
    "ideal_parallel_plates": {
        "status": "supported",
        "confidence": "C2 for configurations; the model itself is literature-benchmarked (C5 checks in the validation suite)",
        "source": "Casimir, Proc. K. Ned. Akad. Wet. 51 (1948) 793; "
                  "Brown & Maclay, Phys. Rev. 184 (1969) 1272",
    },
    **{name: {"status": "model_unavailable",
              "note": "extension interface registered; no supported implementation"}
       for name in (
           "finite_conductivity", "finite_temperature", "layered_materials",
           "dielectric_boundaries", "roughness_corrections",
           "rectangular_cavity", "cylindrical_cavity", "spherical_shell",
           "corrugated_surfaces", "repulsive_configurations", "cavity_arrays",
           "time_dependent_boundaries", "dynamical_casimir",
       )},
}


@dataclass
class CasimirResult:
    model: str
    model_version: str
    validity: str                  # "idealized" | "speculative"
    separation_m: float
    plate_area_m2: float
    gap_count: int
    energy_per_area_j_m2: float    # per gap
    total_energy_j: float          # all gaps
    energy_density_j_m3: float     # in-gap renormalized density
    force_per_area_pa: float       # per gap (negative = attractive)
    force_per_gap_n: float
    pressure_pa: float
    stress_tensor_diag_j_m3: list[float]
    spatial_support: dict
    energy_account: EnergyAccount
    quantum_inequality_status: str = "not_evaluated"
    warnings: list[str] = field(default_factory=list)
    confidence: ConfidenceLevel = ConfidenceLevel.C2_SUPPORTED_APPROXIMATION


class CasimirModelError(ValueError):
    pass


def ideal_parallel_plates(
    separation_m: float,
    plate_area_m2: float,
    plate_count: int = 2,
    temperature_k: float = 0.0,
    apparatus_rest_energy_j: float = 0.0,
    support_energy_j: float = 0.0,
) -> CasimirResult:
    if separation_m <= 0 or plate_area_m2 <= 0 or plate_count < 2:
        raise CasimirModelError("separation and area must be positive; plate_count ≥ 2")

    a = separation_m
    gaps = plate_count - 1
    coeff = math.pi**2 * HBAR * C_LIGHT

    e_per_area = -coeff / (720 * a**3)
    u = -coeff / (720 * a**4)
    f_per_area = -coeff / (240 * a**4)
    total_e = e_per_area * plate_area_m2 * gaps

    warnings = []
    validity = "idealized"
    confidence = ConfidenceLevel.C2_SUPPORTED_APPROXIMATION
    if a < ROUGHNESS_LIMIT_M:
        validity = "speculative"
        confidence = ConfidenceLevel.C1_EXPLORATORY_PROXY
        warnings.append(
            f"separation {a:.2e} m < {ROUGHNESS_LIMIT_M:.0e} m: surface "
            "roughness and plasma-wavelength effects dominate; the ideal-"
            "conductor model is not valid here — result is speculative")
    elif a < CONDUCTIVITY_NOTE_LIMIT_M:
        warnings.append(
            "finite-conductivity corrections of order 5–15% are expected at "
            "this separation for real metals; the correction model is "
            "unavailable (extension interface 'finite_conductivity')")
    if a > CONDUCTIVITY_NOTE_LIMIT_M:
        warnings.append(
            "thermal corrections become significant for separations ≳ 1 µm "
            "at laboratory temperatures; computed at T = 0")
    if temperature_k > THERMAL_NOTE_TEMPERATURE_K:
        warnings.append(
            f"configured temperature {temperature_k} K > 0: the finite-"
            "temperature model is unavailable; result computed at T = 0 "
            "(extension interface 'finite_temperature')")
    if plate_count > 2:
        warnings.append(
            "multi-plate array modeled as independent ideal gaps; interior "
            "plates of an equal-spacing array experience cancelling net "
            "forces from adjacent gaps")

    account = EnergyAccount(
        local_min_energy_density_j_m3=u,
        integrated_vacuum_energy_j=total_e,
        apparatus_rest_energy_j=apparatus_rest_energy_j,
        support_energy_j=support_energy_j,
        total_system_energy_j=apparatus_rest_energy_j + support_energy_j + total_e,
        vacuum_reference="free_space",
    )

    return CasimirResult(
        model="ideal_parallel_plates",
        model_version=MODULE_VERSION,
        validity=validity,
        separation_m=a,
        plate_area_m2=plate_area_m2,
        gap_count=gaps,
        energy_per_area_j_m2=e_per_area,
        total_energy_j=total_e,
        energy_density_j_m3=u,
        force_per_area_pa=f_per_area,
        force_per_gap_n=f_per_area * plate_area_m2,
        pressure_pa=f_per_area,
        stress_tensor_diag_j_m3=[u, -u, -u, 3 * u],
        spatial_support={
            "description": "slab gaps between adjacent plates (sharp support; "
                           "edge smearing is not modeled — see design US-4)",
            "gap_volume_m3": plate_area_m2 * a * gaps,
        },
        energy_account=account,
        warnings=warnings,
        confidence=confidence,
    )


def vacuum_contribution(result: CasimirResult, source_id: str) -> StressEnergyContribution:
    """Package a Casimir result as a stress-energy contribution.
    ⟨T_μν⟩ diag in the gap frame; SI J/m³ with the geometrized factor recorded."""
    u = result.energy_density_j_m3
    return StressEnergyContribution(
        source_component_id=source_id,
        contribution_type="vacuum",
        tensor_form="covariant <T_munu> = (pi^2 hbar c / 720 a^4) diag(-1, 1, 1, -3), "
                "signature -+++, z normal to plates (Brown-Maclay)",
        tensor_diag_si_j_m3=[u, -u, -u, 3 * u],
        geometrized_conversion_factor=G_SI / C_LIGHT**4,
        spatial_support=result.spatial_support,
        approximation=f"ideal conductor, T=0 ({result.model}@{result.model_version}); "
                      f"validity: {result.validity}",
        confidence=result.confidence,
        warnings=list(result.warnings),
    )

"""Staged solver funnel (design §6).

Gate 0  schema + topology validation      — implemented
Gate 1  engineering sanity                — implemented
Gate 2  fast physical approximations      — implemented (Newtonian,
                                            gravitomagnetic, ideal Casimir)
Gate 3  numerical field evaluation        — explicit not_implemented
Gate 4  stationary GR solve               — explicit not_implemented
Gate 5  dynamic evolution                 — explicit not_implemented

A configuration that fails a gate stops there; the analysis records the
highest completed gate and every check that ran. Hard constraint checks in
Gate 1 are not part of scoring and cannot be optimized away.
"""

from __future__ import annotations

import time

from forge_matter import casimir, classical
from forge_matter.compiler import C_LIGHT, CompileError, compile_configuration
from forge_matter.entities import (
    ConfidenceLevel, EnergyAccount, GateReport, GateStatus, MatterAnalysis,
    MatterConfiguration, ScoreVector, StressEnergyContribution,
)
from forge_domain.entities import utcnow

FUNNEL_VERSION = "0.1.0"


def _check(name: str, passed: bool, detail: str, hard: bool = True) -> dict:
    return {"name": name, "passed": passed, "detail": detail, "hard": hard}


def gate0_validate(config: MatterConfiguration) -> tuple[GateReport, dict | None]:
    t0 = time.monotonic()
    checks = []
    phenotype = None
    try:
        phenotype = compile_configuration(config)
        checks.append(_check("compile", True,
                             f"phenotype hash {phenotype['phenotype_hash'][:12]}"))
        status = GateStatus.PASSED
        warnings = list(phenotype["warnings"])
        if warnings:
            status = GateStatus.FLAGGED
    except CompileError as exc:
        checks.append(_check("compile", False, str(exc)))
        status = GateStatus.FAILED
        warnings = []
    return GateReport(gate=0, name="schema_and_topology", status=status,
                      checks=checks, warnings=warnings,
                      duration_s=time.monotonic() - t0), phenotype


def gate1_engineering(config: MatterConfiguration, phenotype: dict) -> GateReport:
    t0 = time.monotonic()
    checks = []
    warnings = []
    cons = phenotype.get("constraints", {})
    totals = phenotype["totals"]

    max_mass = cons.get("maximum_total_mass_kg")
    if max_mass is not None:
        ok = totals["mass_kg"] <= max_mass
        checks.append(_check("total_mass", ok,
                             f"{totals['mass_kg']:.4g} kg vs limit {max_mass:.4g} kg"))
    else:
        checks.append(_check("total_mass", True,
                             f"{totals['mass_kg']:.4g} kg (no constraint)", hard=False))

    speed_frac = cons.get("maximum_component_speed_fraction_c")
    for comp in phenotype["components"]:
        v = comp.get("rim_speed_m_s", 0.0)
        if speed_frac is not None:
            ok = v <= speed_frac * C_LIGHT
            checks.append(_check(f"speed:{comp['id']}", ok,
                                 f"rim speed {v:.4g} m/s vs limit "
                                 f"{speed_frac:.4g}c = {speed_frac*C_LIGHT:.4g} m/s"))
        if comp.get("hoop_stress_pa", 0.0) > 0 and "tensile_strength_pa" in comp:
            sf_req = comp["safety_factor_required"]
            allowed = comp["tensile_strength_pa"] / sf_req
            ok = comp["hoop_stress_pa"] <= allowed
            checks.append(_check(
                f"hoop_stress:{comp['id']}", ok,
                f"σ ≈ {comp['hoop_stress_pa']:.4g} Pa vs tensile/{sf_req:g} = "
                f"{allowed:.4g} Pa ({comp['material_id']}, thin-ring approx)"))
            margin = allowed / comp["hoop_stress_pa"] if comp["hoop_stress_pa"] else float("inf")
            if ok and margin < 1.5:
                warnings.append(f"{comp['id']}: stress margin only {margin:.2f}×")

    stored = totals["rotational_energy_j"]
    max_e = cons.get("maximum_stored_energy_j")
    if max_e is not None:
        checks.append(_check("stored_energy", stored <= max_e,
                             f"{stored:.4g} J vs limit {max_e:.4g} J"))

    failed = [c for c in checks if c["hard"] and not c["passed"]]
    status = GateStatus.FAILED if failed else (
        GateStatus.FLAGGED if warnings else GateStatus.PASSED)
    return GateReport(gate=1, name="engineering_sanity", status=status,
                      checks=checks, warnings=warnings,
                      duration_s=time.monotonic() - t0)


def gate2_fast_physics(config: MatterConfiguration, phenotype: dict,
                       analysis: MatterAnalysis) -> GateReport:
    t0 = time.monotonic()
    checks = []
    warnings = []

    # classical matter contributions (rest-mass energy density, per component)
    for comp in phenotype["components"]:
        rho_e = comp["mean_density_kg_m3"] * C_LIGHT**2
        analysis.contributions.append(StressEnergyContribution(
            source_component_id=comp["id"],
            contribution_type="matter",
            tensor_form="dust: covariant T_00 = rho c^2 (orthonormal rest frame, "
                        "-+++), pressure terms unmodeled at Gate 2",
            tensor_diag_si_j_m3=[rho_e, 0.0, 0.0, 0.0],
            geometrized_conversion_factor=casimir.G_SI / C_LIGHT**4,
            spatial_support={"component": comp["id"], "volume_m3": comp["volume_m3"]},
            approximation="mean-density dust; motion energy tracked separately",
            confidence=ConfidenceLevel.C2_SUPPORTED_APPROXIMATION,
        ))
        if comp["motion"] == "rotation":
            analysis.contributions.append(StressEnergyContribution(
                source_component_id=comp["id"],
                contribution_type="motion",
                tensor_form="rotational kinetic energy (integrated scalar at "
                            "Gate 2; full T^0_i arrives with Gate 3 grids)",
                spatial_support={"component": comp["id"],
                                 "rotational_energy_j": comp["rotational_energy_j"],
                                 "angular_momentum_kg_m2_s": comp["angular_momentum_kg_m2_s"]},
                approximation="rigid rotation",
                confidence=ConfidenceLevel.C2_SUPPORTED_APPROXIMATION,
            ))

    # quantum-vacuum contributions
    vacuum_total = 0.0
    local_min = None
    for ps in phenotype["plate_systems"]:
        result = casimir.ideal_parallel_plates(
            separation_m=ps["separation_m"],
            plate_area_m2=ps["plate_area_m2"],
            plate_count=ps["plate_count"],
            temperature_k=ps["temperature_k"],
            apparatus_rest_energy_j=phenotype["totals"]["rest_energy_j"],
            support_energy_j=phenotype["totals"]["rotational_energy_j"],
        )
        analysis.contributions.append(casimir.vacuum_contribution(result, ps["id"]))
        vacuum_total += result.total_energy_j
        u = result.energy_density_j_m3
        local_min = u if local_min is None else min(local_min, u)
        warnings.extend(f"{ps['id']}: {w}" for w in result.warnings)
        checks.append(_check(
            f"casimir:{ps['id']}", True,
            f"{result.gap_count} gap(s) at a={ps['separation_m']:.3e} m: "
            f"u={u:.4e} J/m^3, F/A={result.force_per_area_pa:.4e} Pa, "
            f"validity={result.validity}", hard=False))

    # observed effects
    analysis.effects.extend(classical.newtonian_gravity(phenotype))
    analysis.effects.extend(classical.frame_dragging(phenotype))
    for e in analysis.effects:
        warnings.extend(f"{e.observation_region_id}/{e.effect}: {w}" for w in e.warnings)

    analysis.energy_account = EnergyAccount(
        local_min_energy_density_j_m3=local_min,
        integrated_vacuum_energy_j=vacuum_total,
        apparatus_rest_energy_j=phenotype["totals"]["rest_energy_j"],
        support_energy_j=phenotype["totals"]["rotational_energy_j"],
        total_system_energy_j=phenotype["totals"]["rest_energy_j"]
        + phenotype["totals"]["rotational_energy_j"] + vacuum_total,
    )

    fd = [e.value for e in analysis.effects
          if e.effect == "frame_dragging_rate_rad_s" and e.value is not None]
    analysis.scores = ScoreVector(
        effect={
            "max_frame_dragging_rate_rad_s": max(fd) if fd else 0.0,
            "min_vacuum_energy_density_j_m3": local_min if local_min is not None else 0.0,
            "integrated_vacuum_energy_j": vacuum_total,
        },
        cost={
            "total_mass_kg": phenotype["totals"]["mass_kg"],
            "stored_energy_j": phenotype["totals"]["rotational_energy_j"],
        },
        safety=(
            {"min_stress_margin": min(margins)}
            if (margins := [
                c["tensile_strength_pa"] / c["safety_factor_required"] / c["hoop_stress_pa"]
                for c in phenotype["components"]
                if c.get("hoop_stress_pa") and "tensile_strength_pa" in c])
            else {}  # no stressed components — omit rather than claim infinite margin
        ),
        confidence_floor=min(
            (c.confidence for c in analysis.contributions),
            default=ConfidenceLevel.C2_SUPPORTED_APPROXIMATION),
    )

    return GateReport(gate=2, name="fast_physical_approximations",
                      status=GateStatus.FLAGGED if warnings else GateStatus.PASSED,
                      checks=checks, warnings=warnings,
                      duration_s=time.monotonic() - t0)


def _stub_gate(n: int, name: str) -> GateReport:
    return GateReport(gate=n, name=name, status=GateStatus.NOT_IMPLEMENTED,
                      checks=[_check("availability", False,
                                     "scheduled — see docs/matter-forge-design.md §6 "
                                     "and docs/backlog.md", hard=False)])


def run_funnel(config: MatterConfiguration, max_gate: int = 2,
               seed: int = 0) -> MatterAnalysis:
    analysis = MatterAnalysis(
        configuration_id=config.id,
        genome_hash=config.genome_hash,
        phenotype_hash="", compiler_version="",
        material_db_version="", random_seed=seed,
    )
    g0, phenotype = gate0_validate(config)
    analysis.gates.append(g0)
    if g0.status == GateStatus.FAILED or phenotype is None:
        analysis.status = "rejected_gate_0"
        analysis.completed_at = utcnow()
        return analysis
    analysis.phenotype_hash = phenotype["phenotype_hash"]
    analysis.compiler_version = phenotype["compiler_version"]
    analysis.material_db_version = phenotype["material_db_version"]
    analysis.highest_gate_completed = 0
    analysis.warnings.extend(phenotype["warnings"])

    if max_gate >= 1:
        g1 = gate1_engineering(config, phenotype)
        analysis.gates.append(g1)
        if g1.status == GateStatus.FAILED:
            analysis.status = "rejected_gate_1"
            analysis.completed_at = utcnow()
            return analysis
        analysis.highest_gate_completed = 1

    if max_gate >= 2:
        g2 = gate2_fast_physics(config, phenotype, analysis)
        analysis.gates.append(g2)
        analysis.highest_gate_completed = 2
        analysis.warnings.extend(g2.warnings)

    for n, name in ((3, "numerical_field_evaluation"),
                    (4, "stationary_gr_solve"), (5, "dynamic_evolution")):
        if max_gate >= n:
            analysis.gates.append(_stub_gate(n, name))

    analysis.status = "completed"
    analysis.completed_at = utcnow()
    return analysis

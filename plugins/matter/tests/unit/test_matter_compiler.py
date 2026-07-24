"""Compiler: determinism, physics validation, engineering rejection."""

import copy
import math

import pytest

from forge_matter.compiler import CompileError, compile_configuration, load_configuration
from forge_matter.funnel import run_funnel


def base_genome(**overrides):
    g = {
        "name": "test_apparatus", "version": "0.1.0",
        "coordinate_system": {"type": "cartesian", "units": "SI"},
        "components": [{
            "id": "ring", "shape": {"type": "torus", "major_radius_m": 1.2,
                                    "minor_radius_m": 0.2},
            "material": {"model": "homogeneous", "material_id": "tungsten"},
            "motion": {"type": "rotation", "axis": [0, 0, 1],
                       "angular_velocity_rad_s": 100.0},
        }],
        "observation_regions": [
            {"id": "axial", "type": "point", "position": [0, 0, 3.0]}],
    }
    g.update(overrides)
    return g


def test_deterministic_phenotype_hash():
    a = compile_configuration(load_configuration(base_genome()))
    b = compile_configuration(load_configuration(base_genome()))
    assert a["phenotype_hash"] == b["phenotype_hash"]
    assert a == b


def test_hash_sensitive_to_physics_change():
    g2 = base_genome()
    g2["components"][0]["motion"]["angular_velocity_rad_s"] = 101.0
    a = compile_configuration(load_configuration(base_genome()))
    b = compile_configuration(load_configuration(g2))
    assert a["phenotype_hash"] != b["phenotype_hash"]


def test_torus_mass_and_inertia():
    p = compile_configuration(load_configuration(base_genome()))
    comp = p["components"][0]
    vol = 2 * math.pi**2 * 1.2 * 0.2**2
    assert comp["volume_m3"] == pytest.approx(vol, rel=1e-12)
    assert comp["mass_kg"] == pytest.approx(19300 * vol, rel=1e-12)
    I_expected = comp["mass_kg"] * (1.2**2 + 0.75 * 0.2**2)
    assert comp["moment_of_inertia_kg_m2"] == pytest.approx(I_expected, rel=1e-6)


def test_superluminal_rotation_rejected():
    g = base_genome()
    g["components"][0]["motion"]["angular_velocity_rad_s"] = 3e8  # rim speed >> c
    with pytest.raises(CompileError, match="superluminal"):
        compile_configuration(load_configuration(g))


def test_relativistic_rim_speed_warns():
    g = base_genome()
    g["components"][0]["motion"]["angular_velocity_rad_s"] = 3e6  # ~0.014c rim
    p = compile_configuration(load_configuration(g))
    assert any("rigid-body" in w for w in p["warnings"])


def test_declared_density_must_match_database():
    g = base_genome()
    g["components"][0]["material"] = {
        "model": "homogeneous", "material_id": "tungsten",
        "density_kg_m3": 10000,  # >5% off from 19300
    }
    with pytest.raises(CompileError, match="deviates"):
        compile_configuration(load_configuration(g))


def test_graded_density_conserves_mass_when_mean_preserved():
    """Redistribution with the same volume-weighted mean keeps total mass."""
    def genome_with_profile(profile, params):
        g = base_genome()
        g["components"][0]["material"] = {
            "model": "graded", "base_material_id": "steel_304",
            "density_profile": profile, "profile_parameters": params,
        }
        return g

    flat = compile_configuration(load_configuration(
        genome_with_profile("rho0 * (1 + 0 * r_normalized)", {})))
    # rho0*(1 + g*(r - 3/4)) has volume-weighted mean rho0 over the unit ball
    # since <r>_volume = ∫r·r²dr/∫r²dr = 3/4
    graded = compile_configuration(load_configuration(
        genome_with_profile("rho0 * (1 + gradient * (r_normalized - 0.75))",
                            {"gradient": 0.5})))
    assert graded["components"][0]["mass_kg"] == pytest.approx(
        flat["components"][0]["mass_kg"], rel=2e-3)


def test_negative_density_profile_rejected():
    g = base_genome()
    g["components"][0]["material"] = {
        "model": "graded", "base_material_id": "steel_304",
        "density_profile": "rho0 * (r_normalized - 0.5)", "profile_parameters": {},
    }
    with pytest.raises(CompileError, match="non-positive"):
        compile_configuration(load_configuration(g))


def test_hostile_profile_expression_rejected():
    g = base_genome()
    g["components"][0]["material"] = {
        "model": "graded", "base_material_id": "steel_304",
        "density_profile": "__import__('os').system('id')",
    }
    with pytest.raises(CompileError, match="invalid density profile"):
        compile_configuration(load_configuration(g))


def test_em_systems_explicitly_unsupported():
    g = base_genome()
    g["electromagnetic_systems"] = [{"id": "coil", "type": "solenoid"}]
    with pytest.raises(CompileError, match="unsupported"):
        load_configuration(g)


def test_gate1_rejects_overstressed_ring():
    g = base_genome()
    # tungsten ring at 3000 rad/s: sigma = rho w^2 R^2 ≈ 3.4e11 Pa >> limit
    g["components"][0]["motion"]["angular_velocity_rad_s"] = 3000.0
    analysis = run_funnel(load_configuration(g))
    assert analysis.status == "rejected_gate_1"
    failed = [c for gate in analysis.gates for c in gate.checks
              if c["name"].startswith("hoop_stress") and not c["passed"]]
    assert failed


def test_gate1_enforces_speed_constraint():
    g = base_genome(constraints={"maximum_component_speed_fraction_c": 1e-9})
    analysis = run_funnel(load_configuration(g))
    assert analysis.status == "rejected_gate_1"

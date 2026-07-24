"""Classical-matter validation (Matter Forge §27): Newtonian and weak-field
frame-dragging behavior against known physics."""

import math

import pytest

from forge_matter.classical import C_LIGHT, G_SI
from forge_matter.compiler import compile_configuration, load_configuration
from forge_matter.funnel import run_funnel

pytestmark = pytest.mark.validation


def sphere_genome(radius=0.5, obs=(0, 0, 2.0), extra_components=(), **kw):
    return {
        "name": "classical_case", "version": "0.1.0",
        "coordinate_system": {"type": "cartesian", "units": "SI"},
        "components": [{
            "id": "ball", "shape": {"type": "sphere", "radius_m": radius},
            "material": {"model": "homogeneous", "material_id": "tungsten"},
        }, *extra_components],
        "observation_regions": [
            {"id": "obs", "type": "point", "position": list(obs)}],
        **kw,
    }


def effect(analysis, name, region="obs"):
    return next(e for e in analysis.effects
                if e.effect == name and e.observation_region_id == region)


def test_uniform_sphere_newtonian_exterior():
    """g = GM/r² outside a uniform sphere."""
    analysis = run_funnel(load_configuration(sphere_genome()))
    assert analysis.status == "completed"
    p = compile_configuration(load_configuration(sphere_genome()))
    M = p["components"][0]["mass_kg"]
    g = effect(analysis, "newtonian_g_m_s2")
    assert g.value == pytest.approx(G_SI * M / 2.0**2, rel=1e-12)


def test_shell_theorem_interior_is_exactly_zero():
    genome = {
        "name": "shell_case", "version": "0.1.0",
        "coordinate_system": {"type": "cartesian", "units": "SI"},
        "components": [{
            "id": "shell", "shape": {"type": "spherical_shell",
                                     "outer_radius_m": 1.0, "thickness_m": 0.05},
            "material": {"model": "homogeneous", "material_id": "steel_304"},
        }],
        "observation_regions": [
            {"id": "inside", "type": "point", "position": [0.3, 0.2, 0.1]},
            {"id": "outside", "type": "point", "position": [0, 0, 3.0]}],
    }
    analysis = run_funnel(load_configuration(genome))
    assert effect(analysis, "newtonian_g_m_s2", "inside").value == 0.0
    p = compile_configuration(load_configuration(genome))
    M = p["components"][0]["mass_kg"]
    assert effect(analysis, "newtonian_g_m_s2", "outside").value == pytest.approx(
        G_SI * M / 9.0, rel=1e-12)


def rotating_shell_genome(omega, obs=(0, 0, 0)):
    return {
        "name": "rotating_shell", "version": "0.1.0",
        "coordinate_system": {"type": "cartesian", "units": "SI"},
        "components": [{
            "id": "shell", "shape": {"type": "spherical_shell",
                                     "outer_radius_m": 1.0, "thickness_m": 0.02},
            "material": {"model": "homogeneous", "material_id": "steel_304"},
            "motion": {"type": "rotation", "axis": [0, 0, 1],
                       "angular_velocity_rad_s": omega},
        }],
        "observation_regions": [
            {"id": "obs", "type": "point", "position": list(obs)}],
    }


def test_rotating_shell_interior_frame_dragging_formula():
    """Ω = 4GMω/(3c²R) inside a thin rotating shell, linear in ω.
    ω kept low enough that 2ω still passes the Gate-1 hoop-stress check —
    over-stressed variants are correctly rejected before Gate 2."""
    omega = 50.0
    analysis = run_funnel(load_configuration(rotating_shell_genome(omega)))
    p = compile_configuration(load_configuration(rotating_shell_genome(omega)))
    M = p["components"][0]["mass_kg"]
    expected = 4 * G_SI * M * omega / (3 * C_LIGHT**2 * 1.0)
    fd = effect(analysis, "frame_dragging_rate_rad_s")
    assert fd.value == pytest.approx(expected, rel=1e-12)
    # linearity in omega
    a2 = run_funnel(load_configuration(rotating_shell_genome(2 * omega)))
    assert effect(a2, "frame_dragging_rate_rad_s").value == pytest.approx(
        2 * fd.value, rel=1e-12)


def test_exterior_frame_dragging_r_cubed_falloff():
    """On-axis exterior dipole: Ω = 2GJ/(c²r³)."""
    def at(z):
        a = run_funnel(load_configuration(rotating_shell_genome(100.0, obs=(0, 0, z))))
        return effect(a, "frame_dragging_rate_rad_s").value
    v3, v6 = at(3.0), at(6.0)
    assert v3 / v6 == pytest.approx(8.0, rel=1e-9)
    p = compile_configuration(load_configuration(rotating_shell_genome(100.0)))
    J = p["totals"]["angular_momentum_z_kg_m2_s"]
    assert v3 == pytest.approx(2 * G_SI * J / (C_LIGHT**2 * 27.0), rel=1e-9)


def test_counter_rotation_cancels_net_dragging():
    genome = {
        "name": "counter_rotating", "version": "0.1.0",
        "coordinate_system": {"type": "cartesian", "units": "SI"},
        "components": [
            {"id": "ring_a",
             "shape": {"type": "torus", "major_radius_m": 1.0, "minor_radius_m": 0.1},
             "material": {"model": "homogeneous", "material_id": "steel_304"},
             "motion": {"type": "rotation", "axis": [0, 0, 1],
                        "angular_velocity_rad_s": 50.0}},
            {"id": "ring_b",
             "shape": {"type": "torus", "major_radius_m": 1.0, "minor_radius_m": 0.1},
             "material": {"model": "homogeneous", "material_id": "steel_304"},
             "motion": {"type": "rotation", "axis": [0, 0, 1],
                        "angular_velocity_rad_s": -50.0}},
        ],
        "observation_regions": [
            {"id": "obs", "type": "point", "position": [0, 0, 5.0]}],
    }
    p = compile_configuration(load_configuration(genome))
    assert p["totals"]["angular_momentum_z_kg_m2_s"] == pytest.approx(0.0, abs=1e-9)
    analysis = run_funnel(load_configuration(genome))
    assert effect(analysis, "frame_dragging_rate_rad_s").value == pytest.approx(0.0, abs=1e-30)


def test_confidence_never_exceeds_c2_at_gate2():
    analysis = run_funnel(load_configuration(rotating_shell_genome(100.0)))
    assert all(int(e.confidence) <= 2 for e in analysis.effects)
    assert all(int(c.confidence) <= 2 for c in analysis.contributions)

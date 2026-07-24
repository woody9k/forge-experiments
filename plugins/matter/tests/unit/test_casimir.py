"""Casimir module: literature benchmarks, scaling, consistency, semantics."""

import math

import pytest

from forge_matter.casimir import (
    HBAR, C_LIGHT, MODELS, CasimirModelError, ideal_parallel_plates,
)
from forge_matter.entities import ConfidenceLevel


def test_literature_value_force_at_100nm():
    """Published benchmark: |F/A| = π²ħc/240a⁴ ≈ 13.0 Pa at a = 100 nm
    (e.g. Lamoreaux, Rep. Prog. Phys. 68 (2005) 201, ideal-metal formula)."""
    r = ideal_parallel_plates(separation_m=1e-7, plate_area_m2=1.0)
    assert r.force_per_area_pa == pytest.approx(-13.0018, rel=1e-4)
    assert r.force_per_area_pa < 0  # attractive


def test_literature_value_energy_at_100nm():
    """E/A = −π²ħc/720a³ ≈ −0.4334 µJ/m² at a = 100 nm."""
    r = ideal_parallel_plates(separation_m=1e-7, plate_area_m2=1.0)
    assert r.energy_per_area_j_m2 == pytest.approx(-4.33375e-7, rel=1e-4)


def test_inverse_fourth_power_scaling():
    r1 = ideal_parallel_plates(1e-7, 1.0)
    r2 = ideal_parallel_plates(2e-7, 1.0)
    assert r1.force_per_area_pa / r2.force_per_area_pa == pytest.approx(16.0, rel=1e-12)
    assert r1.energy_density_j_m3 / r2.energy_density_j_m3 == pytest.approx(16.0, rel=1e-12)
    assert r1.energy_per_area_j_m2 / r2.energy_per_area_j_m2 == pytest.approx(8.0, rel=1e-12)


def test_force_is_energy_derivative():
    """F/A must equal −d(E/A)/da (numeric central difference)."""
    a, h = 1e-7, 1e-12
    e = lambda x: ideal_parallel_plates(x, 1.0).energy_per_area_j_m2
    dE_da = (e(a + h) - e(a - h)) / (2 * h)
    f = ideal_parallel_plates(a, 1.0).force_per_area_pa
    assert f == pytest.approx(-dE_da, rel=1e-6)


def test_stress_tensor_trace_and_structure():
    """Covariant ⟨T_μν⟩ = (π²ħc/720a⁴)diag(−1,1,1,−3) must be traceless
    under η^μν contraction (conformal EM field): −T₀₀+Tₓₓ+Tᵧᵧ+T_zz = 0."""
    r = ideal_parallel_plates(1e-7, 1.0)
    u = r.energy_density_j_m3
    t = r.stress_tensor_diag_j_m3
    assert t == [u, -u, -u, 3 * u]
    trace = -t[0] + t[1] + t[2] + t[3]  # η = diag(−1,1,1,1)
    assert trace == pytest.approx(0.0, abs=abs(u) * 1e-12)
    assert t[3] == pytest.approx(3 * u, rel=1e-12)  # normal stress pulls plates together


def test_multi_plate_array_gap_count():
    r = ideal_parallel_plates(1e-7, 1e-4, plate_count=128)
    assert r.gap_count == 127
    single = ideal_parallel_plates(1e-7, 1e-4, plate_count=2)
    assert r.total_energy_j == pytest.approx(127 * single.total_energy_j, rel=1e-12)
    assert any("cancelling net forces" in w for w in r.warnings)


def test_energy_account_totals_and_warning():
    rest = 1e13
    r = ideal_parallel_plates(1e-7, 1e-4, apparatus_rest_energy_j=rest)
    a = r.energy_account
    assert a.local_min_energy_density_j_m3 < 0
    assert a.integrated_vacuum_energy_j < 0
    assert a.total_system_energy_j == pytest.approx(
        rest + a.integrated_vacuum_energy_j)
    assert a.total_system_energy_j > 0  # apparatus dominates, always shown
    assert "does not imply" in a.warning


def test_sub_roughness_separation_is_speculative():
    r = ideal_parallel_plates(5e-9, 1.0)
    assert r.validity == "speculative"
    assert r.confidence == ConfidenceLevel.C1_EXPLORATORY_PROXY
    assert any("not valid" in w for w in r.warnings)


def test_finite_temperature_warns_and_computes_at_zero():
    cold = ideal_parallel_plates(1e-7, 1.0, temperature_k=0.0)
    warm = ideal_parallel_plates(1e-7, 1.0, temperature_k=300.0)
    assert warm.energy_density_j_m3 == cold.energy_density_j_m3
    assert any("finite_temperature" in w for w in warm.warnings)


def test_invalid_inputs_rejected():
    with pytest.raises(CasimirModelError):
        ideal_parallel_plates(-1e-7, 1.0)
    with pytest.raises(CasimirModelError):
        ideal_parallel_plates(1e-7, 1.0, plate_count=1)


def test_unsupported_models_are_explicit():
    assert MODELS["spherical_shell"]["status"] == "model_unavailable"
    assert MODELS["dynamical_casimir"]["status"] == "model_unavailable"
    assert MODELS["ideal_parallel_plates"]["status"] == "supported"


def test_quantum_inequality_hook_present_but_not_evaluated():
    r = ideal_parallel_plates(1e-7, 1.0)
    assert r.quantum_inequality_status == "not_evaluated"

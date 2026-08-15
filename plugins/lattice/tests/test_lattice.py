import math

import pytest

from forge_lattice.model import C, LatticeInputError, simulate_stack


def test_uniform_material_has_uniform_field_and_expected_energy():
    result = simulate_stack({"layer_count": 4, "layer_thickness_m": 1e-3,
        "frequency_hz": 1e3, "dc_field_v_m": 100.0,
        "rf_field_amplitude_v_m": 0.0, "area_m2": 2.0,
        "materials": {"mg_zn": {"conductivity_s_m": 10.0},
                      "bi": {"conductivity_s_m": 10.0}}})
    assert [x["dc_field_v_m"] for x in result["layers"]] == pytest.approx([100.0] * 4)
    assert result["totals"]["em_mass_equivalent_kg"] == pytest.approx(result["totals"]["em_energy_j"] / C**2)


def test_series_dc_field_is_larger_in_less_conductive_bismuth():
    result = simulate_stack({"layer_count": 2, "dc_field_v_m": 10.0})
    assert result["layers"][1]["dc_field_v_m"] > result["layers"][0]["dc_field_v_m"]
    assert sum(x["dc_field_v_m"] for x in result["layers"]) / 2 == pytest.approx(10.0)


def test_rf_voltage_constraint_and_outputs_are_json_safe():
    result = simulate_stack({"layer_count": 6, "rf_field_amplitude_v_m": 321.0})
    phasors = [x["rf_field_amplitude_v_m"] * complex(math.cos(x["rf_phase_rad"]), math.sin(x["rf_phase_rad"])) for x in result["layers"]]
    assert abs(sum(phasors) / 6) == pytest.approx(321.0)
    assert isinstance(result["effective_properties"]["rf_complex_admittivity_s_m"], dict)


@pytest.mark.parametrize("bad", [{"layer_count": 1}, {"layer_count": 2.5},
                                  {"frequency_hz": 0},
                                  {"dc_field_v_m": float("nan")},
                                  {"materials": {"unobtainium": {}}}])
def test_invalid_or_unbounded_inputs_are_rejected(bad):
    with pytest.raises(LatticeInputError):
        simulate_stack(bad)


def test_claim_language_is_conservative():
    gravity = simulate_stack({})["interpretation"]["gravity"].lower()
    assert "not a prediction" in gravity
    assert "anomalous gravity" in gravity

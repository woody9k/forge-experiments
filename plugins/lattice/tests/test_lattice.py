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


# --------------------------------------------- review findings, pinned as tests

def test_a_perfect_insulator_is_refused_rather_than_clamped():
    """The DC divider is conduction-limited, so sigma = 0 has no answer here.

    It used to be clamped to 1e-30. That looks right for a *single* insulator
    (all the field lands on it, which is the correct limit) and is wrong the
    moment there are two: equal clamped weights divide the field 1:1 where
    the physics says 1/epsilon_r. A plausible number, no warning — the exact
    failure mode the platform forbids.
    """
    with pytest.raises(LatticeInputError, match="conduction-limited"):
        simulate_stack({"layer_count": 2,
                        "materials": {"bi": {"conductivity_s_m": 0.0}}})

    with pytest.raises(LatticeInputError, match="conduction-limited"):
        simulate_stack({"layer_count": 2, "materials": {
            "mg_zn": {"conductivity_s_m": 0.0, "relative_permittivity": 1.0},
            "bi": {"conductivity_s_m": 0.0, "relative_permittivity": 10.0}}})


def test_a_lossy_dielectric_still_works_and_takes_almost_all_the_field():
    """Refusing exactly zero must not refuse the physically useful case."""
    result = simulate_stack({"layer_count": 2, "dc_field_v_m": 10.0,
                             "materials": {"bi": {"conductivity_s_m": 1e-9}}})

    conductor, dielectric = result["layers"]
    assert dielectric["dc_field_v_m"] > 0.999 * 2 * 10.0
    assert conductor["dc_field_v_m"] < 1e-6 * dielectric["dc_field_v_m"]


def test_the_record_carries_every_input_its_outputs_depend_on():
    """The weak-field scale divides by the observation distance, which the
    record did not echo — so the number could not be reproduced from it."""
    result = simulate_stack({"observation_distance_m": 2.5})

    assert result["inputs"]["observation_distance_m"] == 2.5
    scale = result["totals"]["weak_field_acceleration_scale_m_s2"]
    G, mass = 6.674_30e-11, result["totals"]["em_mass_equivalent_kg"]
    assert scale == pytest.approx(G * mass / 2.5**2)


def test_the_sage_tool_raises_the_error_the_audit_layer_catches():
    """`call_tool` writes the failed-attempt audit row inside its
    `except ToolExecutionError` handler, so a bare RuntimeError would escape
    and leave no record of the attempt at all."""
    from apps.coordinator.sage_tools import ToolExecutionError
    from forge_lattice.app.sage_tools import TOOLS

    (_spec, handler), = TOOLS
    with pytest.raises(ToolExecutionError):
        handler(None, {"layer_count": 1})

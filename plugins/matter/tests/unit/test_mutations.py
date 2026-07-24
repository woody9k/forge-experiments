"""Mutation operators: determinism, lineage integrity, scaling reproduction."""

import pytest

from forge_matter.compiler import load_configuration
from forge_matter.funnel import run_funnel
from forge_matter.mutations import MutationError, mutate


def casimir_genome(sep=1e-7):
    return {
        "name": "casimir_stack", "version": "0.1.0",
        "coordinate_system": {"type": "cartesian", "units": "SI"},
        "quantum_boundaries": [{
            "id": "stack", "type": "parallel_plate_array",
            "plate_count": 2, "plate_area_m2": 1e-4, "separation_m": sep,
            "plate_thickness_m": 1e-4, "plate_material_id": "gold",
        }],
        "observation_regions": [
            {"id": "center", "type": "point", "position": [0, 0, 0]}],
    }


def test_mutation_is_deterministic_from_seed():
    parent = load_configuration(casimir_genome())
    a = mutate(parent, "alter_separation", {"target": "stack"}, seed=7)
    b = mutate(parent, "alter_separation", {"target": "stack"}, seed=7)
    c = mutate(parent, "alter_separation", {"target": "stack"}, seed=8)
    assert a.genome_hash == b.genome_hash
    assert a.genome_hash != c.genome_hash


def test_mutation_records_full_lineage():
    parent = load_configuration(casimir_genome())
    child = mutate(parent, "alter_separation", {"target": "stack", "factor": 0.5},
                   seed=1, reason="halve the gap")
    assert child.parent_ids == [parent.id]
    assert child.generation == 1
    m = child.mutation_history[-1]
    assert m.operator == "alter_separation"
    assert m.parameters_before == {"separation_m": 1e-7}
    assert m.parameters_after == {"separation_m": 5e-8}
    assert m.affected_components == ["stack"]
    grandchild = mutate(child, "alter_plate_count", {"target": "stack", "delta": 3}, seed=2)
    assert grandchild.generation == 2
    assert len(grandchild.mutation_history) == 2


def test_parent_genome_is_never_modified():
    parent = load_configuration(casimir_genome())
    before = parent.genome_hash
    mutate(parent, "alter_separation", {"target": "stack", "factor": 2.0}, seed=1)
    assert parent.compute_genome_hash() == before


def test_halving_separation_reproduces_expected_scaling():
    """The §34 vertical path: mutate separation, verify the known a⁻⁴
    energy-density and a⁻³ total-energy scaling between parent and child."""
    parent = load_configuration(casimir_genome())
    child = mutate(parent, "alter_separation", {"target": "stack", "factor": 0.5}, seed=1)
    pa = run_funnel(parent)
    ca = run_funnel(child)
    pu = pa.energy_account.local_min_energy_density_j_m3
    cu = ca.energy_account.local_min_energy_density_j_m3
    assert cu / pu == pytest.approx(16.0, rel=1e-9)      # u ∝ a⁻⁴
    pe = pa.energy_account.integrated_vacuum_energy_j
    ce = ca.energy_account.integrated_vacuum_energy_j
    assert ce / pe == pytest.approx(8.0, rel=1e-9)       # E ∝ a⁻³


def test_identity_mutation_rejected():
    parent = load_configuration(casimir_genome())
    with pytest.raises(MutationError, match="identical"):
        mutate(parent, "alter_separation", {"target": "stack", "factor": 1.0}, seed=1)


def test_invalid_targets_and_operators_rejected():
    parent = load_configuration(casimir_genome())
    with pytest.raises(MutationError, match="no quantum boundary"):
        mutate(parent, "alter_separation", {"target": "nope"}, seed=1)
    with pytest.raises(MutationError, match="unknown operator"):
        mutate(parent, "warp_speed", {}, seed=1)
    with pytest.raises(MutationError, match="< 2"):
        mutate(parent, "alter_plate_count", {"target": "stack", "delta": -1}, seed=1)


def test_bounds_enforced():
    parent = load_configuration(casimir_genome())
    with pytest.raises(MutationError, match="below bound"):
        mutate(parent, "alter_separation", {"target": "stack", "value": 1e-12}, seed=1)

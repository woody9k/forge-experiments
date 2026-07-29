#!/usr/bin/env python3
"""Matter Forge §34 vertical-path demonstration.

Parallel-plate configuration → validation → ideal Casimir calculation →
vacuum stress-energy → local/total energy accounting → force and pressure →
mutation of plate separation → comparison with parent → lineage +
reproducibility export. Then the rotating classical-matter validation case.

Everything printed here is also written to reproducible bundles under
experiments/matter-*/ and persisted in the database.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.coordinator import store
import forge_matter.app.store as mstore  # noqa: E402
from forge_matter.app.runner import analyze_and_bundle, compare_with_parent  # noqa: E402
from forge_matter.compiler import load_configuration  # noqa: E402
from forge_matter.mutations import mutate  # noqa: E402

CASIMIR_GENOME = {
    "name": "casimir_stack_demo", "version": "0.1.0",
    "description": "Vertical-path demo: 2 gold plates, 100 nm gap, 1 cm^2",
    "coordinate_system": {"type": "cartesian", "units": "SI"},
    "quantum_boundaries": [{
        "id": "stack", "type": "parallel_plate_array",
        "plate_count": 2, "plate_area_m2": 1e-4, "separation_m": 1e-7,
        "plate_thickness_m": 1e-4, "material_model": "ideal_conductor",
        "plate_material_id": "gold", "temperature_k": 0.0,
    }],
    "observation_regions": [
        {"id": "center", "type": "point", "position": [0, 0, 0]}],
}

ROTATING_GENOME = {
    "name": "rotating_shell_demo", "version": "0.1.0",
    "description": "Classical validation: thin rotating steel shell, "
                   "frame dragging at the center",
    "coordinate_system": {"type": "cartesian", "units": "SI"},
    "components": [{
        "id": "shell",
        "shape": {"type": "spherical_shell", "outer_radius_m": 1.0,
                  "thickness_m": 0.02},
        "material": {"model": "homogeneous", "material_id": "steel_304"},
        "motion": {"type": "rotation", "axis": [0, 0, 1],
                   "angular_velocity_rad_s": 50.0},
    }],
    "observation_regions": [
        {"id": "center", "type": "point", "position": [0, 0, 0]},
        {"id": "axial_3m", "type": "point", "position": [0, 0, 3.0]}],
}


def banner(text: str) -> None:
    print(f"\n{'=' * 72}\n{text}\n{'=' * 72}")


def show(analysis) -> None:
    print(f"  status: {analysis.status}, highest gate: {analysis.highest_gate_completed}")
    for g in analysis.gates:
        print(f"  gate {g.gate} {g.name}: {g.status.value}")
    for e in analysis.effects:
        val = f"{e.value:.6e}" if e.value is not None else "not computable"
        print(f"  effect [{e.observation_region_id}] {e.effect} = "
              f"{val} {e.units}  (C{int(e.confidence)}, {e.model})")
    a = analysis.energy_account
    if a:
        print(f"  energy account: local min u = {a.local_min_energy_density_j_m3} J/m^3")
        print(f"                  vacuum total = {a.integrated_vacuum_energy_j:.6e} J")
        print(f"                  apparatus rest = {a.apparatus_rest_energy_j:.6e} J")
        print(f"                  TOTAL SYSTEM  = {a.total_system_energy_j:.6e} J")
        print(f"  note: {a.warning}")


def main() -> int:
    banner("1. Casimir vertical path: parent (a = 100 nm)")
    parent = load_configuration(CASIMIR_GENOME)
    mstore.save_matter_configuration(parent)
    parent_analysis, parent_bundle = analyze_and_bundle(parent)
    mstore.save_matter_analysis(parent_analysis)
    show(parent_analysis)
    vac = [c for c in parent_analysis.contributions if c.contribution_type == "vacuum"][0]
    print(f"  vacuum <T_munu> diag = {vac.tensor_diag_si_j_m3} J/m^3")
    print(f"  bundle: {parent_bundle}")

    banner("2. Mutate: halve the plate separation (seed 42)")
    child = mutate(parent, "alter_separation",
                   {"target": "stack", "factor": 0.5}, seed=42,
                   reason="vertical-path demo: expect u x16, E_vac x8")
    mstore.save_matter_configuration(child)
    child_analysis, child_bundle = analyze_and_bundle(child)
    mstore.save_matter_analysis(child_analysis)
    show(child_analysis)

    banner("3. Compare child with parent (expected: u x16, E_vac x8 at a/2)")
    cmp_ = compare_with_parent(parent_analysis, child_analysis)
    u = cmp_["local_min_energy_density_j_m3"]
    e = cmp_["vacuum_energy_j"]
    print(f"  u:     {u['parent']:.6e} -> {u['child']:.6e}  "
          f"(ratio {u['child']/u['parent']:.3f}, expected 16.000)")
    print(f"  E_vac: {e['parent']:.6e} -> {e['child']:.6e}  "
          f"(ratio {e['child']/e['parent']:.3f}, expected 8.000)")
    print(f"  lineage: {child.id[:12]} <- {parent.id[:12]} via "
          f"{child.mutation_history[-1].operator}"
          f"@{child.mutation_history[-1].operator_version}")

    banner("4. Rotating classical-matter validation case")
    rot = load_configuration(ROTATING_GENOME)
    mstore.save_matter_configuration(rot)
    rot_analysis, rot_bundle = analyze_and_bundle(rot)
    mstore.save_matter_analysis(rot_analysis)
    show(rot_analysis)
    print(f"  bundle: {rot_bundle}")

    ok = all(a.status == "completed"
             for a in (parent_analysis, child_analysis, rot_analysis))
    ratio_ok = abs(u["child"] / u["parent"] - 16.0) < 1e-6
    print(f"\nvertical path {'REPRODUCED' if ok and ratio_ok else 'FAILED'}: "
          f"known effect computed, mutated, rescaled as published theory predicts.")
    return 0 if ok and ratio_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

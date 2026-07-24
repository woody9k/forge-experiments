"""Matter Forge API integration: the §34 vertical path over HTTP.

parallel-plate configuration → validation → Casimir calculation → vacuum
stress-energy → energy accounting → force/pressure → mutation → parent
comparison → lineage → reproducible bundle.
"""

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

GENOME = {
    "name": "casimir_stack", "version": "0.1.0",
    "coordinate_system": {"type": "cartesian", "units": "SI"},
    "quantum_boundaries": [{
        "id": "stack", "type": "parallel_plate_array",
        "plate_count": 2, "plate_area_m2": 1e-4, "separation_m": 1e-7,
        "plate_thickness_m": 1e-4, "material_model": "ideal_conductor",
        "plate_material_id": "gold", "temperature_k": 4.0,
    }],
    "observation_regions": [
        {"id": "center", "type": "point", "position": [0, 0, 0]}],
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_EAGER", "1")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/forge-test.db")
    monkeypatch.setenv("EXPERIMENTS_DIR", str(tmp_path / "experiments"))
    for mod in [m for m in list(sys.modules) if m.startswith("apps.")]:
        del sys.modules[mod]
    from fastapi.testclient import TestClient
    from apps.api.main import app
    return TestClient(app)


def test_casimir_vertical_path(client, tmp_path):
    # create + validate
    r = client.post("/api/v1/matter/configurations", json=GENOME)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    v = client.post(f"/api/v1/matter/configurations/{cid}/validate").json()
    assert v["valid"] is True

    # simulate through gates 0–2
    s = client.post(f"/api/v1/matter/configurations/{cid}/simulate").json()
    assert s["status"] == "completed"
    assert s["highest_gate_completed"] == 2

    # vacuum stress-energy + five-part energy account
    se = client.get(f"/api/v1/matter/configurations/{cid}/stress-energy").json()
    vac = [c for c in se["contributions"] if c["contribution_type"] == "vacuum"]
    assert len(vac) == 1
    diag = vac[0]["tensor_diag_si_j_m3"]
    assert diag[0] < 0 and diag[3] == pytest.approx(3 * diag[0])
    acct = se["energy_account"]
    assert acct["local_min_energy_density_j_m3"] == pytest.approx(-4.3338, rel=1e-3)
    assert acct["total_system_energy_j"] > 0
    assert "does not imply" in acct["warning"]

    # mutate separation ×2 and verify the known a⁻⁴/a⁻³ scaling via compare
    m = client.post(f"/api/v1/matter/configurations/{cid}/mutate", json={
        "operator": "alter_separation",
        "params": {"target": "stack", "factor": 2.0},
        "seed": 42, "reason": "vertical-path demonstration",
    })
    assert m.status_code == 201, m.text
    child_id = m.json()["id"]
    assert m.json()["generation"] == 1
    client.post(f"/api/v1/matter/configurations/{child_id}/simulate")
    cmp_ = client.get(f"/api/v1/matter/configurations/{child_id}/compare-parent").json()
    ratio = (cmp_["local_min_energy_density_j_m3"]["child"]
             / cmp_["local_min_energy_density_j_m3"]["parent"])
    assert ratio == pytest.approx(1 / 16, rel=1e-9)

    # lineage
    lin = client.get(f"/api/v1/matter/configurations/{child_id}/lineage").json()
    assert lin["ancestors"][0]["id"] == cid
    assert lin["mutation_history"][0]["operator"] == "alter_separation"
    parent_lin = client.get(f"/api/v1/matter/configurations/{cid}/lineage").json()
    assert any(ch["id"] == child_id for ch in parent_lin["children"])

    # reproducible bundle exists with checksummed manifest
    bundles = list((tmp_path / "experiments").glob("matter-*"))
    assert len(bundles) == 2
    manifest = json.loads((bundles[0] / "manifest.json").read_text())
    assert manifest["kind"] == "matter_analysis"
    assert manifest["artifact_checksums"]
    from apps.coordinator.provenance import file_checksum
    for name, digest in manifest["artifact_checksums"].items():
        assert file_checksum(bundles[0] / name) == digest


def test_campaign_execution_is_honestly_gated(client):
    spec = {
        "name": "maximize_frame_dragging",
        "objective": {"primary": {"metric": "frame_dragging_rate_rad_s",
                                  "direction": "maximize"}},
        "constraints": {"maximum_total_mass_kg": 5000},
        "search": {"strategy": "random", "random_seed": 1},
    }
    r = client.post("/api/v1/matter/campaigns", json=spec)
    assert r.status_code == 501
    assert "B-2" in json.dumps(r.json())

    bad = dict(spec, search={"strategy": "quantum_annealing", "random_seed": 1})
    assert client.post("/api/v1/matter/campaigns", json=bad).status_code == 422


def test_hostile_matter_configuration_rejected(client):
    evil = dict(GENOME)
    evil["components"] = [{
        "id": "blob", "shape": {"type": "sphere", "radius_m": 1.0},
        "material": {"model": "graded", "base_material_id": "steel_304",
                     "density_profile": "__import__('os').system('id')"},
    }]
    r = client.post("/api/v1/matter/configurations", json=evil)
    assert r.status_code == 201  # stored as draft…
    cid = r.json()["id"]
    v = client.post(f"/api/v1/matter/configurations/{cid}/validate").json()
    assert v["valid"] is False  # …but never validates or simulates
    assert "not an allowed" in v["error"] or "invalid density profile" in v["error"]


def test_gate3_plus_request_rejected_explicitly(client):
    r = client.post("/api/v1/matter/configurations", json=GENOME)
    cid = r.json()["id"]
    resp = client.post(f"/api/v1/matter/configurations/{cid}/simulate?max_gate=4")
    assert resp.status_code == 422
    assert "not implemented" in resp.json()["detail"]

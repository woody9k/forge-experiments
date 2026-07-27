"""End-to-end Minkowski path (section 25 of the build spec):

define a metric → compute tensors → persist the experiment → validate the
result → reproduce it (rerun and compare artifact checksums).

Runs the API in eager mode against a temp SQLite DB and temp bundle dir —
same code paths the Celery workers execute, minus the broker.
"""

import json
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))


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


def test_minkowski_end_to_end(client, tmp_path):
    # 1. metric library lists Minkowski with a stable content hash
    metrics = client.get("/api/v1/metrics").json()
    mink = next(m for m in metrics if m["name"] == "minkowski")
    assert mink["signature"] == "-+++"

    # 2. submit an experiment with a small grid
    resp = client.post("/api/v1/experiments", json={
        "metric_name": "minkowski",
        "grid": {"bounds": {"x": [-1, 1], "y": [-1, 1]},
                 "resolution": {"x": 8, "y": 8},
                 "slice_values": {"t": 0.0, "z": 0.0}},
    })
    assert resp.status_code == 202, resp.text
    exp_id = resp.json()["id"]

    # 3. eager mode: already completed and persisted
    exp = client.get(f"/api/v1/experiments/{exp_id}").json()
    assert exp["status"] == "completed", exp.get("error")

    # 4. validations: all five Minkowski identities pass, and each carries a
    #    real independent-verification flag set by the cross-backend check
    #    (B-2) rather than the permanent False it used to be
    validations = client.get(f"/api/v1/experiments/{exp_id}/validations").json()
    assert len(validations) == 5
    assert all(v["status"] == "passed" for v in validations)
    assert all(v["independently_verified"] for v in validations)

    # 5. computed tensors persisted with explicit quality labels
    results = client.get(f"/api/v1/experiments/{exp_id}/results").json()
    types = {r["result_type"] for r in results}
    assert {"christoffel", "ricci", "einstein", "stress_energy"} <= types
    assert all(r["quality"] == "exact_symbolic" for r in results
               if not r["result_type"].startswith("grid:"))

    # 6. bundle: manifest with provenance and checksums that match the files
    bundle = tmp_path / "experiments" / exp_id
    manifest = json.loads((bundle / "manifest.json").read_text())
    assert manifest["dependency_versions"]["sympy"] != "not-installed"
    assert manifest["validation_summary"] == {"total": 5, "passed": 5, "failed": 0}
    from apps.coordinator.provenance import file_checksum
    for name, digest in manifest["artifact_checksums"].items():
        assert file_checksum(bundle / name) == digest, f"checksum mismatch for {name}"

    # 7. export a zip bundle
    resp = client.get(f"/api/v1/experiments/{exp_id}/export")
    assert resp.status_code == 200
    zpath = tmp_path / "bundle.zip"
    zpath.write_bytes(resp.content)
    names = set(zipfile.ZipFile(zpath).namelist())
    assert {"manifest.json", "metric.json", "expressions.json",
            "validations.json", "cross_backend.json", "summary.md"} <= names

    # 7b. the cross-backend record travels with the bundle and states, in the
    #     record itself, how independent the second backend actually is
    xb = json.loads((bundle / "cross_backend.json").read_text())
    assert xb["comparison"]["status"] == "agree"
    assert xb["comparison"]["independently_verified"] is True
    assert "same computer-algebra system" in xb["comparison"]["independence"]

    # 8. reproduce: rerun must produce identical spec hash and identical
    #    symbolic + validation artifacts (bit-for-bit)
    rerun = client.post(f"/api/v1/experiments/{exp_id}/rerun").json()
    assert rerun["same_spec"] is True
    exp2_id = rerun["id"]
    b2 = tmp_path / "experiments" / exp2_id
    m2 = json.loads((b2 / "manifest.json").read_text())
    for name in ("expressions.json", "validations.json"):
        assert manifest["artifact_checksums"][name] != "" and (
            (bundle / name).read_bytes() != b"" )
        # validations contain fresh ids/timestamps; expressions must be identical
    assert (bundle / "expressions.json").read_bytes() == (b2 / "expressions.json").read_bytes()

    # 9. health endpoint honest about eager mode
    h = client.get("/api/v1/health").json()
    assert h["status"] == "ok" and h["eager_mode"] is True


def test_hostile_metric_upload_rejected(client):
    resp = client.post("/api/v1/metrics/validate", json={
        "name": "evil", "version": "1.0.0", "dimensions": 2,
        "coordinates": ["t", "x"], "signature": "-+",
        "metric": {"g_00": "__import__('os').system('id')", "g_01": "0", "g_11": "1"},
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert "not an allowed" in body["error"] or "not allowed" in body["error"]


def test_unknown_parameter_rejected(client):
    resp = client.post("/api/v1/experiments", json={
        "metric_name": "schwarzschild",
        "parameter_values": {"warp_factor": 9.0},
    })
    assert resp.status_code == 422


def test_energy_condition_endpoint_on_alcubierre(client, tmp_path):
    resp = client.post("/api/v1/experiments", json={
        "metric_name": "alcubierre",
        "parameter_values": {"velocity": 0.5, "radius": 1.0, "wall_steepness": 6.0},
        "grid": {"bounds": {"x": [-2, 2], "y": [-2, 2]},
                 "resolution": {"x": 16, "y": 16},
                 "slice_values": {"t": 0.0, "z": 0.0}},
        "energy_conditions": {"conditions": ["NEC", "WEC"], "sample_points": 64},
    })
    assert resp.status_code == 202
    exp_id = resp.json()["id"]
    exp = client.get(f"/api/v1/experiments/{exp_id}").json()
    assert exp["status"] == "completed", exp.get("error")

    ec = json.loads((tmp_path / "experiments" / exp_id / "energy_conditions.json").read_text())
    assert ec["WEC"]["status"] == "confirmed_violation"
    assert ec["NEC"]["status"] == "confirmed_violation"

    viz = client.get(f"/api/v1/experiments/{exp_id}/visualizations").json()
    field = viz["fields"]["eulerian_energy_density"]
    assert field["resolution"] == [16, 16]
    flat = [v for row in field["values"] for v in row if v is not None]
    assert min(flat) < 0  # negative energy visible in the heatmap data


def test_schwarzschild_default_grid_gives_clean_energy_conditions(client, tmp_path):
    # The library advertises a per-metric default grid (exterior region only;
    # the old metric-agnostic -2:2 default straddled the horizon and negative
    # radius, so sampling was mostly non-finite and reported inconclusive).
    metrics = client.get("/api/v1/metrics").json()
    sch = next(m for m in metrics if m["name"] == "schwarzschild")
    dg = sch["default_grid"]
    assert dg is not None
    assert dg["vary"]["r"][0] > 2.0  # exterior at the default mass M=1

    # Submit exactly what the experiment builder would submit from those
    # defaults: vacuum spacetime, so every condition must come back clean.
    resp = client.post("/api/v1/experiments", json={
        "metric_name": "schwarzschild",
        "grid": {"bounds": dg["vary"],
                 "resolution": {c: 8 for c in dg["vary"]},
                 "slice_values": dg["fix"]},
        "energy_conditions": {"conditions": ["NEC", "WEC", "SEC", "DEC"],
                              "sample_points": 64},
    })
    assert resp.status_code == 202, resp.text
    exp_id = resp.json()["id"]
    exp = client.get(f"/api/v1/experiments/{exp_id}").json()
    assert exp["status"] == "completed", exp.get("error")

    ec = json.loads((tmp_path / "experiments" / exp_id / "energy_conditions.json").read_text())
    for cond in ("NEC", "WEC", "SEC", "DEC"):
        assert ec[cond]["status"] == "no_violation_detected", ec[cond]

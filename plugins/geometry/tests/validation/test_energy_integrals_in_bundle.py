"""The energy integrals reach the bundle, and the volume element is real.

`forge_math/energy.py` shipped with B-16 part 1 and was imported by nothing
but its own unit test — the arithmetic was pinned, the *pipeline* was not.
These tests drive the actual runner, because every failure mode this wiring
can have (the metric not reaching the integrator, the wrong axes, the file
not being checksummed) is invisible to a test that calls the module directly.

The discriminating case is Natário against Alcubierre. Alcubierre's spatial
3-metric is flat — the whole distortion lives in the lapse and shift — so its
proper and coordinate integrals *must* agree exactly, and chart sensitivity
is exactly 1. Natário is written in a spherical chart whose spatial block is
diag(1, r²), so the volume element is not 1 and the two measures must
differ. If those two runs ever report the same chart sensitivity, the volume
element is not being applied in the runner path, which is the single most
likely way this wiring breaks silently.
"""

from __future__ import annotations

import json
import os

import pytest

from forge_geometry.app.runner import execute_experiment
from forge_geometry.entities import Experiment, GridSpec
from forge_metrics import builtin_metrics, load_metric_file

pytestmark = [pytest.mark.validation, pytest.mark.slow]


def _run(name: str, resolution: int = 16):
    """Execute one bundled metric over its own default grid."""
    parsed = load_metric_file(builtin_metrics()[name])
    definition = parsed.definition
    default = definition.default_grid
    assert default is not None, f"{name} has no default grid to sample"
    grid = GridSpec(
        bounds={k: list(v) for k, v in default.vary.items()},
        resolution={k: resolution for k in default.vary},
        slice_values=dict(default.fix),
    )
    experiment = Experiment(
        metric_name=name, metric_version=definition.version,
        metric_hash=definition.hash,
        parameter_values={k: v.default for k, v in definition.parameters.items()},
        grid=grid,
    )
    run, manifest = execute_experiment(experiment)
    report = json.loads((run.bundle_dir / "energy_integrals.json").read_text())
    return run, manifest, report


@pytest.fixture(scope="module")
def bundle_root(tmp_path_factory):
    """Bundles go to a temp directory, not the checkout's ``experiments/``.

    Module-scoped because each of these runs costs a full symbolic pipeline;
    ``monkeypatch`` is function-scoped, so the variable is swapped by hand.
    """
    previous = os.environ.get("EXPERIMENTS_DIR")
    os.environ["EXPERIMENTS_DIR"] = str(tmp_path_factory.mktemp("bundles"))
    try:
        yield
    finally:
        if previous is None:
            del os.environ["EXPERIMENTS_DIR"]
        else:
            os.environ["EXPERIMENTS_DIR"] = previous


@pytest.fixture(scope="module")
def alcubierre_run(bundle_root):
    return _run("alcubierre")


@pytest.fixture(scope="module")
def natario_run(bundle_root):
    return _run("natario")


# ------------------------------------------------------------------ wiring

def test_the_bundle_carries_the_integrals_and_their_checksum(alcubierre_run):
    run, manifest, report = alcubierre_run

    assert "energy_integrals.json" in manifest["artifact_checksums"]
    assert (manifest["artifact_checksums"]["energy_integrals.json"]
            == run.checksums["energy_integrals.json"])
    # All three measures are always present, so a consumer can never mistake
    # "this measure was not computed" for "this measure is zero".
    assert set(report["integrals"]) == {"coordinate", "proper", "adm"}


def test_a_result_row_points_at_the_integrals(alcubierre_run):
    run, _manifest, _report = alcubierre_run

    rows = [c for c in run.computation_results
            if c.result_type == "grid:energy_integrals"]
    assert len(rows) == 1
    assert rows[0].array_location == "energy_integrals.json"
    assert rows[0].checksum == run.checksums["energy_integrals.json"]
    # A plane integral is an energy per unit length, never an energy.
    assert rows[0].units == "energy_per_unit_length"


def test_a_plane_run_labels_its_dimension_and_refuses_adm(alcubierre_run):
    _run_, _manifest, report = alcubierre_run

    for measure in ("coordinate", "proper"):
        entry = report["integrals"][measure]
        assert entry["available"] is True
        assert entry["dimension"] == 2
        assert entry["unit"] == "energy_per_unit_length"

    adm = report["integrals"]["adm"]
    assert adm["available"] is False
    assert adm["total"] is None  # never 0.0
    assert "3-D spatial slice" in adm["reason"]


# ------------------------------------------------------- the physics content

def test_alcubierre_has_negative_energy_in_both_measures(alcubierre_run):
    _run_, _manifest, report = alcubierre_run

    for measure in ("coordinate", "proper"):
        entry = report["integrals"][measure]
        assert entry["negative_part"] < 0.0
        assert entry["negative_fraction"] > 0.0


def test_alcubierres_flat_spatial_slice_makes_the_measures_agree_exactly(
        alcubierre_run):
    """g_ij = δ_ij, so √det ³g = 1 and the chart costs nothing here.

    Exact equality, not approximate: the weight is literally an array of
    ones, so any difference at all would mean a different set of samples
    reached the two integrals.
    """
    _run_, _manifest, report = alcubierre_run

    coordinate = report["integrals"]["coordinate"]
    proper = report["integrals"]["proper"]
    assert proper["total"] == coordinate["total"]
    assert report["chart_sensitivity"] == 1.0


def test_natarios_spherical_chart_makes_the_measures_disagree(natario_run):
    """The regression guard: a volume element that is silently never applied
    would make this identical to the Alcubierre case above."""
    _run_, _manifest, report = natario_run

    coordinate = report["integrals"]["coordinate"]
    proper = report["integrals"]["proper"]
    assert proper["available"] and coordinate["available"]
    assert proper["total"] != coordinate["total"]
    assert report["chart_sensitivity"] != 1.0
    # Both still find the published WEC violation; the chart changes how much
    # exotic matter you are quoted, not whether any is required.
    assert proper["negative_part"] < 0.0
    assert coordinate["negative_part"] < 0.0

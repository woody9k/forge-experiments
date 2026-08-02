"""The read-only analyser over stored bundles.

Two properties matter and neither is about arithmetic (``energy.py`` owns
that): a bundle that cannot yield an integral is *reported*, never skipped
and never guessed at, and the analyser does not touch the bundles it reads.

The second is the one worth a test. A provenance bundle is a checksummed
artifact stamped with the code that produced it; writing newly-computed
results into one would make its manifest describe a run that never happened
and invalidate every evidence link taken against it. Nothing enforces that
but this test.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from analyze_energy_integrals import analyse  # noqa: E402


def _bundle(root: Path, name: str, *, status: str = "completed",
            arrays: bool = True) -> Path:
    """A minimal bundle in the layout the real runner writes."""
    bundle = root / name
    (bundle / "arrays").mkdir(parents=True)
    (bundle / "manifest.json").write_text(json.dumps({
        "experiment": {"metric_name": "toy", "metric_hash": "abc123",
                       "parameter_values": {"velocity": 0.5},
                       "status": status},
        "source_commit": "deadbeef",
    }))
    (bundle / "metric.json").write_text(json.dumps({
        "coordinates": ["t", "x", "y", "z"], "coordinate_system": "cartesian"}))

    shape = (8, 8)
    density = np.full(shape, -1.5)
    np.savez_compressed(bundle / "arrays" / "energy_density.npz",
                        eulerian_energy_density=density)
    if arrays:
        metric = np.zeros((4, 4, *shape))
        metric[0, 0] = -1.0
        for i in (1, 2, 3):
            metric[i, i] = 1.0
        axis = np.linspace(-1.0, 1.0, 8)
        np.savez_compressed(bundle / "arrays" / "grid.npz",
                            axis_x=axis, axis_y=axis, metric=metric)
    return bundle


def _snapshot(bundle: Path) -> dict[str, bytes]:
    return {str(p.relative_to(bundle)): p.read_bytes()
            for p in sorted(bundle.rglob("*")) if p.is_file()}


def test_a_complete_bundle_yields_all_three_measures(tmp_path):
    bundle = _bundle(tmp_path, "good")

    row = analyse(bundle)

    assert row["available"] is True
    assert set(row["integrals"]) == {"coordinate", "proper", "adm"}
    assert row["integrals"]["coordinate"]["negative_part"] < 0.0
    # Flat spatial metric: the chart costs nothing, exactly as for Alcubierre.
    assert row["chart_sensitivity"] == 1.0
    assert row["spatial_axes"] == ["x", "y"]


def test_reading_a_bundle_does_not_modify_it(tmp_path):
    """The whole design premise of the analyser, asserted rather than
    assumed — a backfill that edited bundles would destroy their provenance."""
    bundle = _bundle(tmp_path, "untouched")
    before = _snapshot(bundle)

    analyse(bundle)

    assert _snapshot(bundle) == before


def test_a_bundle_with_no_metric_on_the_grid_is_reported_not_skipped(tmp_path):
    bundle = _bundle(tmp_path, "gridless", arrays=False)

    row = analyse(bundle)

    assert row["available"] is False
    assert "no arrays/grid.npz" in row["reason"]
    # Identity is still reported, so the run can be found and re-run.
    assert row["experiment_id"] == "gridless"
    assert row["metric"] == "toy"


def test_an_incomplete_run_is_refused_with_its_status(tmp_path):
    bundle = _bundle(tmp_path, "failed-run", status="failed")

    row = analyse(bundle)

    assert row["available"] is False
    assert "'failed'" in row["reason"]


def test_an_unreadable_bundle_does_not_abort_the_sweep(tmp_path):
    bundle = tmp_path / "corrupt"
    (bundle / "arrays").mkdir(parents=True)
    (bundle / "manifest.json").write_text("{not json")

    row = analyse(bundle)

    assert row["available"] is False
    assert "unreadable bundle" in row["reason"]

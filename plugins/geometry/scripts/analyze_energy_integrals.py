#!/usr/bin/env python3
"""Compute energy integrals for runs that predate B-16 part 2 — read-only.

Runs stored before the integrals were wired into the runner have everything
needed to compute them: ``arrays/grid.npz`` has always carried ``metric`` on
the sampled points alongside the stress energy, and ``energy_density.npz``
has the Eulerian density. Only the consumer was missing.

**This deliberately does not write into those bundles.** A provenance bundle
is a self-contained checksummed artifact stamped with the software version
and source commit that produced it. Adding an artifact computed by newer code
would make the manifest describe a run that never happened, silently
invalidate every stored evidence link whose ``manifest_checksum`` was taken
before the edit, and destroy the one property the bundle exists to have. So
the report is a *derived* artifact that references the runs by id and leaves
them untouched.

If you want genuine bundles carrying their own integrals, re-run the
experiments against the current code — new runs, new ids, honest provenance,
and the old ones stay exactly as they were.

Usage:

    EXPERIMENTS_DIR=/data/experiments \\
      python plugins/geometry/scripts/analyze_energy_integrals.py \\
        --out report.json

Add ``--metric alcubierre`` to restrict the sweep, ``--csv sweep.csv`` for a
flat table suited to plotting.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from forge_math.energy import (  # noqa: E402
    EnergyIntegralError, chart_sensitivity, energy_integrals,
)

#: Written into the report so a consumer can tell which code produced it.
ANALYSIS_VERSION = "1"


def _bundles(root: Path):
    for path in sorted(root.iterdir()):
        if (path / "arrays" / "energy_density.npz").is_file():
            yield path


def analyse(bundle: Path) -> dict:
    """One run's three measures, or an explicit reason it has none.

    Never raises on a bad bundle: a sweep over a hundred runs that dies on
    the one corrupt member is less useful than one that reports it.
    """
    row: dict = {"experiment_id": bundle.name}
    try:
        manifest = json.loads((bundle / "manifest.json").read_text())
        definition = json.loads((bundle / "metric.json").read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return {**row, "available": False, "reason": f"unreadable bundle: {exc}"}

    experiment = manifest.get("experiment", {})
    row.update({
        "metric": experiment.get("metric_name"),
        "metric_hash": experiment.get("metric_hash"),
        "coordinate_system": definition.get("coordinate_system"),
        "parameter_values": experiment.get("parameter_values", {}),
        "status": experiment.get("status"),
        "source_commit": manifest.get("source_commit"),
    })
    if row["status"] != "completed":
        return {**row, "available": False,
                "reason": f"run status {row['status']!r} is not 'completed'"}

    grid_path = bundle / "arrays" / "grid.npz"
    if not grid_path.is_file():
        return {**row, "available": False,
                "reason": "no arrays/grid.npz, so no metric on the grid"}

    with np.load(grid_path) as grid, \
            np.load(bundle / "arrays" / "energy_density.npz") as density:
        if "metric" not in grid:
            return {**row, "available": False,
                    "reason": "grid.npz carries no 'metric' array"}
        axes = {k[len("axis_"):]: grid[k] for k in grid if k.startswith("axis_")}
        try:
            integrals = energy_integrals(
                density["eulerian_energy_density"], axes,
                definition["coordinates"], metric=grid["metric"])
        except EnergyIntegralError as exc:
            return {**row, "available": False, "reason": str(exc)}

    row.update({
        "available": True,
        "spatial_axes": list(axes),
        "integrals": {m: r.as_dict() for m, r in integrals.items()},
        "chart_sensitivity": chart_sensitivity(integrals),
    })
    return row


def _csv_rows(rows: list[dict]):
    """Flat table for plotting: one line per run, per-measure columns."""
    for row in rows:
        if not row.get("available"):
            continue
        flat = {
            "experiment_id": row["experiment_id"],
            "metric": row["metric"],
            "coordinate_system": row["coordinate_system"],
            "chart_sensitivity": row["chart_sensitivity"],
            "dimension": row["integrals"]["coordinate"]["dimension"],
            "unit": row["integrals"]["coordinate"]["unit"],
        }
        flat.update({f"param_{k}": v
                     for k, v in row["parameter_values"].items()})
        for measure in ("coordinate", "proper"):
            entry = row["integrals"][measure]
            flat[f"{measure}_total"] = entry["total"]
            flat[f"{measure}_negative_part"] = entry["negative_part"]
            flat[f"{measure}_negative_fraction"] = entry["negative_fraction"]
        yield flat


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--experiments-dir", default=os.environ.get(
        "EXPERIMENTS_DIR", "experiments"))
    parser.add_argument("--metric", help="restrict to one metric name")
    parser.add_argument("--out", help="write the full JSON report here")
    parser.add_argument("--csv", help="write a flat table here")
    args = parser.parse_args()

    root = Path(args.experiments_dir).resolve()
    if not root.is_dir():
        print(f"no such directory: {root}", file=sys.stderr)
        return 2

    rows = [analyse(b) for b in _bundles(root)]
    if args.metric:
        rows = [r for r in rows if r.get("metric") == args.metric]
    usable = [r for r in rows if r.get("available")]

    print(f"{len(rows)} gridded run(s) under {root}; "
          f"{len(usable)} with computable integrals")
    for row in rows:
        if not row.get("available"):
            print(f"  {row['experiment_id'][:12]}  "
                  f"{row.get('metric') or '?':14s} UNAVAILABLE — {row['reason']}")
            continue
        params = ", ".join(f"{k}={v:g}"
                           for k, v in sorted(row["parameter_values"].items()))
        coordinate = row["integrals"]["coordinate"]
        proper = row["integrals"]["proper"]
        # A flat vacuum has no negative part at all, so the ratio is
        # undefined rather than 1 — say so instead of printing a number.
        sensitivity = ("undefined (no negative energy on this grid)"
                       if row["chart_sensitivity"] is None
                       else f"{row['chart_sensitivity']:.6f}")
        print(f"  {row['experiment_id'][:12]}  {row['metric']:14s} {params}")
        print(f"        coordinate {coordinate['negative_part']: .6e}   "
              f"proper {proper['negative_part']: .6e}   "
              f"chart sensitivity {sensitivity}   "
              f"[{coordinate['unit']}]")

    report = {"analysis_version": ANALYSIS_VERSION,
              "experiments_dir": str(root),
              "runs": rows}
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2))
        print(f"\nwrote {args.out}")
    if args.csv:
        flat = list(_csv_rows(rows))
        if flat:
            fields = sorted({k for row in flat for k in row})
            with open(args.csv, "w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(flat)
            print(f"wrote {args.csv} ({len(flat)} row(s))")
        else:
            print("no usable rows; wrote no CSV")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

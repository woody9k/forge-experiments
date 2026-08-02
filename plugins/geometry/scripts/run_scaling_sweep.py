#!/usr/bin/env python3
"""Sweep an Alcubierre parameter axis and fit the exotic-energy scaling law.

The first sweep this platform ran was untrustworthy in two independent ways,
both silent, and this script exists to close both:

**The window did not follow the bubble.** Every run held ``[-2, 2]²`` while
the radius varied up to 2, so the largest bubbles had their wall at the grid
edge. Fixed by ``default_grid.scale_with`` — the window is now resolved per
run from the metric definition.

**The resolution did not follow the wall.** Alcubierre's wall thickness goes
like ``1/sigma``, so a fixed sample count under-resolves exactly the thin-wall
runs a wall-steepness study is *about*. A window of width ``4R`` sampled at
``N`` points has spacing ``4R/N``, so resolving the wall needs
``N >> 4*R*sigma``; at ``R=1, sigma=24`` that is far more than the 32 the
stored runs used. Fixed by ``--points-per-wall``, which sets ``N`` per run.

Neither failure raises. Both return plausible numbers and move the fitted
exponent, which is why this script reports a **convergence check** — the same
sweep at two resolutions — rather than a single fit. An exponent that moves
when you look harder is not a result yet.

Usage:

    python plugins/geometry/scripts/run_scaling_sweep.py --axis wall_steepness
    python plugins/geometry/scripts/run_scaling_sweep.py --axis radius --out r.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from forge_math.energy import chart_sensitivity, energy_integrals  # noqa: E402

#: Axis values swept, per parameter. Chosen to span a decade or so, since a
#: power-law fit over a narrow range is mostly fitting noise.
AXES = {
    "wall_steepness": [4.0, 6.0, 8.0, 12.0, 16.0, 24.0, 32.0],
    "radius": [0.5, 0.75, 1.0, 1.5, 2.0, 3.0],
    "velocity": [0.25, 0.5, 0.75, 1.0, 1.5, 2.0],
}


def _grid_for(definition, parameter_values: dict[str, float],
              points_per_wall: int) -> dict:
    """A window that follows the bubble, sampled fine enough to resolve it.

    ``points_per_wall`` is the number of samples across one wall thickness
    ``1/sigma``. The wall is the entire structure here — the interior and
    exterior are flat — so this, not the window width, is what the integral's
    accuracy depends on.
    """
    from forge_geometry.entities import GridSpec

    bounds = definition.default_grid.resolve(parameter_values)
    sigma = parameter_values["wall_steepness"]
    resolution = {}
    for coordinate, (lo, hi) in bounds.items():
        needed = int(math.ceil((hi - lo) * sigma * points_per_wall))
        # Bounded: below 16 the integral is noise, and the evaluator refuses
        # above 4096 anyway.
        resolution[coordinate] = max(16, min(needed, 512))
    return GridSpec(bounds={k: list(v) for k, v in bounds.items()},
                    resolution=resolution,
                    slice_values=dict(definition.default_grid.fix))


def run_one(definition, parameter_values: dict[str, float],
            points_per_wall: int) -> dict:
    """Execute one experiment and return its integrals, computed in-process."""
    from forge_geometry.app.runner import execute_experiment
    from forge_geometry.entities import Experiment

    grid = _grid_for(definition, parameter_values, points_per_wall)
    experiment = Experiment(
        metric_name=definition.name, metric_version=definition.version,
        metric_hash=definition.hash,
        parameter_values=dict(parameter_values), grid=grid,
    )
    started = time.monotonic()
    run, _manifest = execute_experiment(experiment)
    report = json.loads((run.bundle_dir / "energy_integrals.json").read_text())
    integrals = report["integrals"]
    return {
        "experiment_id": experiment.id,
        "parameter_values": dict(parameter_values),
        "resolution": grid.resolution,
        "bounds": {k: list(v) for k, v in grid.bounds.items()},
        "status": experiment.status.value,
        "seconds": time.monotonic() - started,
        "coordinate_negative_part": integrals["coordinate"]["negative_part"],
        "proper_negative_part": integrals["proper"]["negative_part"],
        "negative_fraction": integrals["coordinate"]["negative_fraction"],
        "chart_sensitivity": report["chart_sensitivity"],
        "warnings": integrals["coordinate"]["warnings"],
    }


def fit(rows: list[dict], axis: str) -> dict | None:
    """Least-squares power-law exponent of |E_neg| against the swept axis."""
    usable = [r for r in rows
              if r["status"] == "completed" and r["proper_negative_part"]]
    if len(usable) < 3:
        return None
    x = np.array([r["parameter_values"][axis] for r in usable])
    y = np.abs([r["proper_negative_part"] for r in usable])
    slope, intercept = np.polyfit(np.log(x), np.log(y), 1)
    predicted = np.exp(intercept) * x ** slope
    residual = np.max(np.abs(predicted / y - 1.0))
    logy = np.log(y)
    r2 = 1.0 - (np.sum((logy - (slope * np.log(x) + intercept)) ** 2)
                / np.sum((logy - logy.mean()) ** 2))
    return {"axis": axis, "exponent": float(slope),
            "coefficient": float(np.exp(intercept)),
            "r_squared": float(r2), "max_relative_residual": float(residual),
            "n": len(usable)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--axis", choices=sorted(AXES), default="wall_steepness")
    parser.add_argument("--points-per-wall", type=int, default=12,
                        help="samples across one wall thickness 1/sigma")
    parser.add_argument("--convergence-factor", type=int, default=2,
                        help="second pass at this multiple of the resolution; "
                             "0 to skip the convergence check")
    parser.add_argument("--out", help="write the full JSON report here")
    args = parser.parse_args()

    from forge_metrics import builtin_metrics, load_metric_file

    definition = load_metric_file(builtin_metrics()["alcubierre"]).definition
    base = {k: p.default for k, p in definition.parameters.items()}

    passes = [args.points_per_wall]
    if args.convergence_factor:
        passes.append(args.points_per_wall * args.convergence_factor)

    report = {"axis": args.axis, "metric": "alcubierre",
              "metric_hash": definition.hash, "fixed": {}, "passes": []}
    report["fixed"] = {k: v for k, v in base.items() if k != args.axis}

    for points in passes:
        print(f"\n=== {args.axis} sweep, {points} points per wall thickness")
        rows = []
        for value in AXES[args.axis]:
            row = run_one(definition, {**base, args.axis: value}, points)
            rows.append(row)
            warn = " ".join(row["warnings"])[:60]
            print(f"  {args.axis}={value:<6g} "
                  f"res={max(row['resolution'].values()):<4d} "
                  f"E_neg={row['proper_negative_part']: .6e} "
                  f"negfrac={row['negative_fraction']:.3f} "
                  f"{row['seconds']:.1f}s {warn}")
        result = fit(rows, args.axis)
        report["passes"].append({"points_per_wall": points, "runs": rows,
                                 "fit": result})
        if result:
            print(f"  fit: |E_neg| ~ {result['coefficient']:.5g} * "
                  f"{args.axis}^{result['exponent']:.4f}   "
                  f"R2={result['r_squared']:.6f}  "
                  f"max residual {result['max_relative_residual']:.2%}")

    fits = [p["fit"] for p in report["passes"] if p["fit"]]
    if len(fits) == 2:
        drift = abs(fits[1]["exponent"] - fits[0]["exponent"])
        report["convergence"] = {
            "exponent_coarse": fits[0]["exponent"],
            "exponent_fine": fits[1]["exponent"],
            "drift": drift,
            # A judgement the reader should be able to check, not a verdict
            # the script hands down.
            "converged_to_2dp": drift < 0.005,
        }
        print(f"\nconvergence: exponent {fits[0]['exponent']:.4f} -> "
              f"{fits[1]['exponent']:.4f}  (drift {drift:.4f})")
        if drift >= 0.005:
            print("  NOT converged — the exponent still moves with resolution; "
                  "raise --points-per-wall before quoting it")

    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2))
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Run a Metric Forge experiment locally, without the service stack.

Examples:
    python scripts/run_experiment.py minkowski
    python scripts/run_experiment.py schwarzschild -p mass=2.0
    python scripts/run_experiment.py alcubierre -p velocity=0.5 \
        --bounds x=-2:2 y=-2:2 --resolution 32 --slice t=0 z=0

Writes a full experiment bundle under experiments/<id>/ and records the
experiment in the local database (DATABASE_URL, default sqlite:///./forge.db).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.coordinator import store
import forge_geometry.app.store as gstore
from forge_geometry.app import runner  # noqa: E402
from forge_domain.entities import ExperimentStatus
from forge_geometry.entities import Experiment, GridSpec  # noqa: E402
from forge_metrics import builtin_metrics, load_metric_file  # noqa: E402


def parse_kv(items: list[str], cast=float) -> dict:
    out = {}
    for item in items:
        k, _, v = item.partition("=")
        if not _:
            raise SystemExit(f"expected key=value, got {item!r}")
        out[k] = cast(v)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("metric", help="bundled metric name (see metrics/)")
    ap.add_argument("-p", "--param", action="append", default=[],
                    help="parameter override, name=value")
    ap.add_argument("--bounds", nargs="*", default=[],
                    help="grid bounds, coord=min:max")
    ap.add_argument("--resolution", type=int, default=32)
    ap.add_argument("--slice", dest="slices", nargs="*", default=[],
                    help="fixed coordinate values, coord=value")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    if args.metric not in builtin_metrics():
        raise SystemExit(f"unknown metric {args.metric!r}; "
                         f"available: {sorted(builtin_metrics())}")

    pm = load_metric_file(builtin_metrics()[args.metric])
    grid = None
    if args.bounds:
        bounds = {}
        for b in args.bounds:
            k, _, rng = b.partition("=")
            lo, _, hi = rng.partition(":")
            bounds[k] = (float(lo), float(hi))
        grid = GridSpec(
            bounds=bounds,
            resolution={k: args.resolution for k in bounds},
            slice_values=parse_kv(args.slices),
        )

    exp = Experiment(
        metric_name=args.metric,
        metric_version=pm.definition.version,
        metric_hash=pm.definition.hash,
        parameter_values=parse_kv(args.param),
        grid=grid,
        random_seed=args.seed,
        status=ExperimentStatus.QUEUED,
    )
    gstore.save_experiment(exp)
    run, manifest = runner.execute_experiment(exp)
    gstore.save_experiment(exp)
    gstore.save_results(run.computation_results, run.validation_results)

    print(f"experiment  {exp.id}")
    print(f"status      {exp.status.value}")
    if exp.error:
        print(f"error       {exp.error}")
    vs = manifest["validation_summary"]
    print(f"validations {vs['passed']}/{vs['total']} passed, {vs['failed']} failed")
    for w in manifest["warnings"]:
        print(f"warning     {w}")
    print(f"bundle      {run.bundle_dir}")
    return 0 if exp.status == ExperimentStatus.COMPLETED and vs["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

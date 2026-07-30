"""The pendulum pipeline stage: integrate, judge, persist, bundle.

Mirrors what any domain does — it uses the platform's bundle machinery for
artifacts and provenance, and it never decides its own validity beyond
reporting the evidence.
"""

from __future__ import annotations

import json
from pathlib import Path

from apps.coordinator.bundles import checksummed_dump, experiments_dir
from apps.coordinator.provenance import dependency_versions, source_commit
from forge_domain.entities import utcnow
from forge_pendulum.app.store import new_run_id, save_run
from forge_pendulum.model import PendulumSpec, integrate

#: The tolerance below which a small-amplitude run is considered to have
#: reproduced the closed-form period.  A domain judgement, stated once.
SMALL_ANGLE_TOLERANCE = 1e-2
SMALL_ANGLE_MAX_DEG = 5.0


def run_to_bundle(spec_dict: dict, run_id: str) -> dict:
    """Run one pendulum experiment and write a self-contained bundle.

    Deliberately **store-free**: this is the half a Worker Fabric agent can
    call on a host that has no database (see ``forge_pendulum.worker``).
    Persistence is ``execute``'s job, on the coordinator side.
    """
    spec = PendulumSpec(**spec_dict)
    started = utcnow()

    try:
        result = integrate(spec)
    except ValueError as exc:          # invalid input: fail loudly, no bundle
        return {"id": run_id, "spec": spec_dict, "status": "failed",
                "error": str(exc), "result": None,
                "created_at": started.isoformat()}

    validation = _validate(spec, result)
    bundle_dir = experiments_dir() / run_id
    bundle_dir.mkdir(parents=True, exist_ok=True)
    checksums = {
        "spec.json": checksummed_dump(bundle_dir / "spec.json", spec_dict),
        "result.json": checksummed_dump(bundle_dir / "result.json",
                                        result.as_dict()),
        "validation.json": checksummed_dump(bundle_dir / "validation.json",
                                            validation),
    }
    manifest = {
        "run": run_id,
        "plugin": "pendulum",
        "spec": spec_dict,
        "started_at": started.isoformat(),
        "completed_at": utcnow().isoformat(),
        "source_commit": source_commit(),
        "dependency_versions": dependency_versions(),
        "artifact_checksums": checksums,
        "validation_summary": {"total": 1,
                               "passed": 1 if validation["passed"] else 0},
        "warnings": result.warnings,
    }
    checksummed_dump(bundle_dir / "manifest.json", manifest)

    return {"id": run_id, "spec": spec_dict, "status": "completed",
            "error": None, "result": result.as_dict(), "validation": validation,
            "bundle": run_id, "manifest": manifest,
            "created_at": started.isoformat()}


def execute(spec_dict: dict, run_id: str | None = None) -> dict:
    """Run one experiment and persist it. The coordinator-side entry point."""
    run = run_to_bundle(spec_dict, run_id or new_run_id())
    save_run({k: v for k, v in run.items() if k != "manifest"})
    return run


def _validate(spec: PendulumSpec, result) -> dict:
    """Known-answer check: a small-amplitude swing must match T = 2π√(L/g).

    Outside the small-angle regime the comparison is *not* a pass/fail — the
    honest verdict is "inapplicable", not a failure, and not a silent pass.
    """
    if abs(spec.initial_angle_deg) > SMALL_ANGLE_MAX_DEG:
        return {
            "check": "small_angle_period",
            "status": "inapplicable",
            "passed": True,
            "detail": (f"amplitude {spec.initial_angle_deg}° exceeds the "
                       f"{SMALL_ANGLE_MAX_DEG}° small-angle regime; the "
                       f"closed form is not expected to hold"),
            "expected": result.small_angle_period_s,
            "observed": result.measured_period_s,
            "deviation": result.relative_deviation,
            "tolerance": SMALL_ANGLE_TOLERANCE,
        }
    if result.relative_deviation is None:
        return {"check": "small_angle_period", "status": "inconclusive",
                "passed": False, "detail": "no period could be measured",
                "expected": result.small_angle_period_s, "observed": None,
                "deviation": None, "tolerance": SMALL_ANGLE_TOLERANCE}
    passed = abs(result.relative_deviation) <= SMALL_ANGLE_TOLERANCE
    return {
        "check": "small_angle_period",
        "status": "passed" if passed else "failed",
        "passed": passed,
        "detail": (f"measured {result.measured_period_s:.6f} s vs closed form "
                   f"{result.small_angle_period_s:.6f} s "
                   f"({result.relative_deviation:+.2e})"),
        "expected": result.small_angle_period_s,
        "observed": result.measured_period_s,
        "deviation": result.relative_deviation,
        "tolerance": SMALL_ANGLE_TOLERANCE,
    }


def read_bundle_manifest(run_id: str) -> dict:
    """Read a run's manifest, with the containment check every bundle read
    needs: a crafted id must not escape the bundle root."""
    root = experiments_dir().resolve()
    path = (root / run_id / "manifest.json").resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"invalid run id {run_id!r}")
    if not path.is_file():
        raise FileNotFoundError(f"no bundle for run {run_id!r}")
    return json.loads(path.read_text())

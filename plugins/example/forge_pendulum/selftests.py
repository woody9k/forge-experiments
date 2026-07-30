"""The worker selftest suite this plugin contributes.

A capability is schedulable only after the agent runs this suite *and* the
coordinator re-verifies the evidence.  So the checks must be deterministic
and their goldens re-checkable server-side — the whole point is that a
worker cannot declare itself fit.
"""

from __future__ import annotations

import time

from forge_pendulum.model import PendulumSpec, integrate, small_angle_period_s
from forge_sdk import SelftestSuite, environment_fingerprint

#: A 1 m pendulum released at 5°: deterministic, sub-second, and its period
#: is a known answer.  Pinned to 9 decimals — the integration is exactly
#: reproducible for a fixed timestep.
_PROBE = PendulumSpec(length_m=1.0, initial_angle_deg=5.0, duration_s=10.0,
                      timestep_s=1e-3)
_GOLDEN_PERIOD_S = 2.007364
_TOLERANCE = 1e-5


def run_pendulum_selftest() -> dict:
    t0 = time.monotonic()
    result = integrate(_PROBE)
    ideal = small_angle_period_s(_PROBE.length_m)
    checks = [
        {"name": "period_matches_golden",
         "passed": result.measured_period_s is not None
                   and abs(result.measured_period_s - _GOLDEN_PERIOD_S) < _TOLERANCE,
         "detail": f"measured {result.measured_period_s}",
         "measured_period_s": result.measured_period_s},
        {"name": "period_near_closed_form",
         "passed": result.relative_deviation is not None
                   and abs(result.relative_deviation) < 1e-3,
         "detail": f"deviation {result.relative_deviation}"},
        {"name": "energy_conserved",
         "passed": result.energy_drift < 1e-3,
         "detail": f"drift {result.energy_drift:.2e}",
         "energy_drift": result.energy_drift},
    ]
    return {
        "suite": "pendulum-cpu-v1",
        "suite_version": "1.0.0",
        "checks": checks,
        "passed": all(c["passed"] for c in checks),
        "runtime_s": time.monotonic() - t0,
        "environment": environment_fingerprint(packages=("pydantic",)),
    }


def _verify(evidence: dict) -> list[str]:
    """Coordinator-side: re-check the reported numbers against the goldens
    rather than trusting the worker's own pass/fail."""
    problems = []
    by_name = {c.get("name"): c for c in evidence.get("checks", [])}
    period = by_name.get("period_matches_golden", {}).get("measured_period_s")
    if not isinstance(period, (int, float)) or \
            abs(period - _GOLDEN_PERIOD_S) >= _TOLERANCE:
        problems.append(f"reported period {period} is not the golden "
                        f"{_GOLDEN_PERIOD_S} within {_TOLERANCE}")
    drift = by_name.get("energy_conserved", {}).get("energy_drift")
    if not isinstance(drift, (int, float)) or drift >= 1e-3:
        problems.append(f"reported energy drift {drift} exceeds 1e-3")
    return problems


SUITES = [
    SelftestSuite(capability="pendulum_integration", name="pendulum-cpu-v1",
                  version="1.0.0", runner=run_pendulum_selftest,
                  verify=_verify),
]

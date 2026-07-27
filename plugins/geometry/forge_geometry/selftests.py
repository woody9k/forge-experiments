"""Geometry worker self-test suites (platform-split Phase 2).

Moved verbatim from ``forge_fabric.selftests``: these known-answer suites
prove a worker host can be trusted with geometry work (Minkowski exact
zeros, Schwarzschild grid residuals, parser security).  They register with
fabric through the plugin registry — fabric itself no longer knows they
exist.  The residual-tolerance check that used to live inline in fabric's
verifier is now this module's ``verify`` hook: suite semantics travel with
the suite.
"""

from __future__ import annotations

import time

from forge_sdk.instruments import SelftestSuite, environment_fingerprint


def run_symbolic_cpu_selftest() -> dict:
    """Minkowski tensors must be exactly zero; hostile parses must fail."""
    import sympy as sp
    from forge_math import compute_geometry
    from forge_metrics import builtin_metrics, load_metric_file
    from forge_sdk.expressions import RestrictedParseError, parse_expression

    t0 = time.monotonic()
    checks = []

    pm = load_metric_file(builtin_metrics()["minkowski"])
    geo = compute_geometry(pm.matrix, pm.coords, simplify_level="full")
    n = geo.dim
    nonzero = sum(
        1 for a in range(n) for b in range(n) for c in range(n) for d in range(n)
        if sp.simplify(geo.riemann_up[a][b][c][d]) != 0)
    checks.append({"name": "minkowski_riemann_zero", "passed": nonzero == 0,
                   "detail": f"{nonzero} nonzero Riemann components"})
    checks.append({"name": "minkowski_einstein_zero",
                   "passed": all(sp.simplify(e) == 0 for e in geo.einstein),
                   "detail": "einstein tensor identically zero"})

    hostile_rejected = 0
    payloads = ["__import__('os')", "().__class__", "open('/etc/passwd')", "x.real"]
    for payload in payloads:
        try:
            parse_expression(payload, {"x": sp.Symbol("x")})
        except RestrictedParseError:
            hostile_rejected += 1
    checks.append({"name": "parser_security_smoke",
                   "passed": hostile_rejected == len(payloads),
                   "detail": f"{hostile_rejected}/{len(payloads)} payloads rejected"})

    return {
        "suite": "symbolic-cpu-v1",
        "suite_version": "1.0.0",
        "checks": checks,
        "passed": all(c["passed"] for c in checks),
        "runtime_s": time.monotonic() - t0,
        "environment": environment_fingerprint(),
    }


def run_numerical_cpu_selftest() -> dict:
    """Evaluate Schwarzschild Kretschmann on a grid vs the closed form."""
    import numpy as np
    from forge_geometry.entities import GridSpec
    from forge_math.numeric import evaluate_on_grid
    from forge_metrics import builtin_metrics, load_metric_file

    t0 = time.monotonic()
    pm = load_metric_file(builtin_metrics()["schwarzschild"])
    r = next(c for c in pm.coords if c.name == "r")
    spec = GridSpec(bounds={"r": (3.0, 10.0)}, resolution={"r": 64},
                    slice_values={"t": 0.0, "theta": np.pi / 2, "phi": 0.0})
    ev = evaluate_on_grid(pm.coords, spec, {"kretschmann": 48 / r**6})
    vals = ev.fields["kretschmann"].values
    expected = 48.0 / ev.axes["r"] ** 6
    residual = float(np.abs(vals - expected).max() / expected.max())
    finite_ok = bool(np.all(np.isfinite(vals)))

    # deliberate finite-policy probe: 1/(r-3) grid crossing its pole must flag
    probe = evaluate_on_grid(pm.coords, GridSpec(
        bounds={"r": (2.0, 4.0)}, resolution={"r": 33},
        slice_values={"t": 0.0, "theta": np.pi / 2, "phi": 0.0}),
        {"pole": 1 / (r - 3)})
    policy_ok = not probe.fields["pole"].finite

    checks = [
        {"name": "known_field_residual", "passed": residual < 1e-12,
         "detail": f"max relative residual {residual:.3e}", "residual": residual},
        {"name": "all_finite", "passed": finite_ok, "detail": "grid values finite"},
        {"name": "finite_value_policy", "passed": policy_ok,
         "detail": "non-finite field correctly flagged, not masked"},
    ]
    return {
        "suite": "numerical-cpu-v1",
        "suite_version": "1.0.0",
        "checks": checks,
        "passed": all(c["passed"] for c in checks),
        "runtime_s": time.monotonic() - t0,
        "environment": environment_fingerprint(),
    }


def _verify_numerical(evidence: dict) -> list[str]:
    """Residual tolerance is suite semantics, so it verifies with the suite."""
    problems = []
    for c in evidence.get("checks", []):
        if c.get("name") == "known_field_residual" and \
                not (isinstance(c.get("residual"), (int, float))
                     and c["residual"] < 1e-12):
            problems.append(
                f"residual {c.get('residual')} outside tolerance 1e-12")
    return problems


SUITES = [
    SelftestSuite(capability="symbolic_sympy", name="symbolic-cpu-v1",
                  version="1.0.0", runner=run_symbolic_cpu_selftest),
    SelftestSuite(capability="numerical_numpy", name="numerical-cpu-v1",
                  version="1.0.0", runner=run_numerical_cpu_selftest,
                  verify=_verify_numerical),
    # Defined, not runnable without GPU hardware (F-5/F-9).
    SelftestSuite(capability="numerical_jax_cuda", name="numerical-cuda-v1",
                  version="1.0.0", runner=None),
]

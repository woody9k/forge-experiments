"""Cross-backend verification, expressed as validation records (B-2).

Runs the independent backend (``forge_verify``) on the same parsed metric the
coordinate pipeline was given, compares the two, and turns the resulting
comparison record into ``ValidationResult`` rows so the epistemic status
travels with everything else the platform stores.

``ValidationResult.independently_verified`` is set here and **only** here.
The rule is deliberately narrow:

* it is set on a cross-backend row only when that quantity's comparison
  concluded ``agree``;
* it is set on a known-answer row (via ``apply_independent_verification``)
  only when *every* compared quantity agreed — i.e. the geometry those
  known-answer checks were computed from was reproduced end-to-end by an
  independently derived implementation.

Anything else — one inconclusive quantity, a backend that raised, a metric
that was never cross-checked — leaves the flag ``False``.  "We could not
decide" must never render as "verified".
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import sympy as sp

from forge_domain.entities import SolverBackend, ValidationResult, ValidationStatus
from forge_math.pipeline import GeometryResult
from forge_metrics.loader import ParsedMetric
from forge_verify import (
    AgreementStatus, CrossBackendComparison, compare_geometries,
    compute_frame_geometry,
)
from forge_verify.frame_curvature import FrameGeometryError
from forge_verify.tetrad import TetradError

BACKEND_A = "sympy_coordinate_pipeline (forge_math.pipeline)"
BACKEND_B = "sympy_orthonormal_frame (forge_verify.frame_curvature)"

# Metrics at or below this SymPy operation count get full simplification and a
# Kretschmann cross-check on the independent path; larger ones (the warp
# family) run lightly reduced, where the comparison leans on seeded numeric
# sampling and says so.
FULL_SIMPLIFY_OP_BUDGET = 40

_STATUS_MAP = {
    AgreementStatus.AGREE: ValidationStatus.PASSED,
    AgreementStatus.DISAGREE: ValidationStatus.FAILED,
    AgreementStatus.INCONCLUSIVE: ValidationStatus.INCONCLUSIVE,
    AgreementStatus.NOT_COMPARED: ValidationStatus.INCONCLUSIVE,
}


@dataclass
class CrossBackendVerification:
    """Everything one cross-backend run produced."""

    comparison: CrossBackendComparison | None
    results: list[ValidationResult] = field(default_factory=list)
    duration_s: float = 0.0
    error: str | None = None

    @property
    def verified(self) -> bool:
        return self.comparison is not None and self.comparison.independently_verified

    def to_dict(self) -> dict:
        return {
            "comparison": self.comparison.to_dict() if self.comparison else None,
            "error": self.error,
            "results": [r.model_dump(mode="json") for r in self.results],
        }


def choose_verify_level(matrix: sp.Matrix) -> tuple[str, bool]:
    """(simplification level, compute Kretschmann) for the independent path."""
    if sum(sp.count_ops(e) for e in matrix) <= FULL_SIMPLIFY_OP_BUDGET:
        return "full", True
    return "light", False


def run_cross_backend_check(
    parsed: ParsedMetric,
    geo: GeometryResult,
    experiment_id: str,
    *,
    simplify_level: str | None = None,
    compute_kretschmann: bool | None = None,
    domains: dict[sp.Symbol, tuple[float, float]] | None = None,
    quantities: tuple[str, ...] | None = None,
) -> CrossBackendVerification:
    """Recompute ``parsed`` independently and compare against ``geo``."""
    level, kret = choose_verify_level(parsed.matrix)
    if simplify_level is not None:
        level = simplify_level
    if compute_kretschmann is not None:
        kret = compute_kretschmann

    t0 = time.monotonic()
    try:
        frame_geo = compute_frame_geometry(
            parsed.matrix, parsed.coords,
            signature=parsed.definition.signature,
            simplify_level=level, compute_kretschmann=kret,
        )
    except (FrameGeometryError, TetradError) as exc:
        # Loud, recorded, and explicitly not verification.
        return CrossBackendVerification(
            comparison=None,
            duration_s=time.monotonic() - t0,
            error=str(exc),
            results=[ValidationResult(
                experiment_id=experiment_id,
                validation_type="cross_backend.independent_backend",
                expected="independent frame backend reproduces the geometry",
                computed=f"backend raised: {exc}",
                tolerance=0.0,
                status=ValidationStatus.COMPUTATION_FAILED,
                evidence="the independent backend could not compute this metric; "
                         "no cross-backend evidence exists either way",
                solver_backend=SolverBackend.SYMPY_TETRAD,
            )],
        )

    kwargs = {}
    if quantities is not None:
        kwargs["quantities"] = quantities
    comparison = compare_geometries(
        geo, frame_geo,
        metric_name=parsed.definition.name,
        backend_a=BACKEND_A, backend_b=BACKEND_B,
        domains=domains, **kwargs,
    )
    duration = time.monotonic() - t0

    results = [
        ValidationResult(
            experiment_id=experiment_id,
            validation_type=f"cross_backend.{q.quantity}",
            expected=f"{BACKEND_B} reproduces {q.quantity} from {BACKEND_A}",
            computed=q.detail,
            tolerance=0.0,
            status=_STATUS_MAP[q.status],
            residual=q.residual,
            evidence=(f"{q.agreeing}/{q.components} components agreed; "
                      f"deciding method: {q.method}; "
                      f"exact={'yes' if q.exact else 'no'}"),
            solver_backend=SolverBackend.SYMPY_TETRAD,
            independently_verified=q.status is AgreementStatus.AGREE,
        )
        for q in comparison.quantities
    ]
    results.append(ValidationResult(
        experiment_id=experiment_id,
        validation_type="cross_backend.summary",
        expected="two independently derived backends agree on every quantity",
        computed=comparison.status.value,
        tolerance=0.0,
        status=_STATUS_MAP[comparison.status],
        evidence=comparison.epistemic_note,
        solver_backend=SolverBackend.SYMPY_TETRAD,
        independently_verified=comparison.independently_verified,
    ))
    return CrossBackendVerification(
        comparison=comparison, results=results, duration_s=duration)


def apply_independent_verification(
    results: list[ValidationResult],
    verification: CrossBackendVerification,
) -> int:
    """Stamp ``independently_verified`` on known-answer results.

    Only applied to results that themselves PASSED, and only when the whole
    cross-backend comparison agreed: the claim being made is "this check was
    computed from a geometry that an independently derived backend
    reproduced", which is false if any part of that geometry is in doubt.
    Returns how many rows were stamped.
    """
    if not verification.verified:
        return 0
    stamped = 0
    for r in results:
        if r.status is ValidationStatus.PASSED and not r.validation_type.startswith(
                "cross_backend."):
            r.independently_verified = True
            stamped += 1
    return stamped

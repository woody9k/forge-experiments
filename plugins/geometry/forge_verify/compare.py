"""Cross-backend comparison records.

Takes the output of two independently derived geometry computations and
produces a structured, self-describing record: which quantities were
compared, the verdict per quantity, *which equivalence method decided each*,
and an explicit epistemic status for the whole comparison.

Three rules this module exists to enforce:

* **Inconclusive is not agreement.**  A quantity nobody could decide is
  reported as ``inconclusive`` and drags the overall verdict down with it.
* **Disagreement is loud.**  A quantity where the backends differ makes the
  whole record ``disagree`` and names the offending components.  This is the
  finding the feature exists to produce, not an error to be smoothed over.
* **Agreement is qualified.**  The record distinguishes agreement proved by
  exact symbolic reduction from agreement supported only by sampling, and it
  carries the honest description of *how independent* the two backends
  actually are (``independence``).

The comparison is duck-typed on both sides: any object exposing
``inverse_metric``/``ricci``/``ricci_scalar``/``einstein``/``stress_energy``
(and optionally ``kretschmann``) works.  Nothing here imports either
pipeline, so neither backend can leak into the referee.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum

import sympy as sp

from forge_verify.equivalence import (
    DEFAULT_SEED, EquivalenceCheck, EquivalenceMethod, Verdict, check_equivalent,
)

# Description of what "independent" means for the pair of backends shipped in
# this repo.  Stated in one place, quoted into every record and every doc, so
# the claim cannot drift.
SHARED_CAS_INDEPENDENCE = (
    "independent implementation and independent derivation route (coordinate "
    "Christoffel/Riemann route vs orthonormal-frame Cartan route), both "
    "evaluated by the same computer-algebra system (SymPy). Catches index, "
    "sign, convention, algebra and transcription errors in either path; does "
    "NOT catch a bug inside SymPy itself, which both paths would inherit."
)

# Kretschmann is included when both backends produced it; a backend that
# deferred it (warp metrics) yields `not_compared`, which is excluded from the
# verdict rather than counted as agreement.
DEFAULT_QUANTITIES = (
    "inverse_metric", "ricci", "ricci_scalar", "einstein", "stress_energy",
    "kretschmann",
)


class AgreementStatus(StrEnum):
    AGREE = "agree"
    DISAGREE = "disagree"
    INCONCLUSIVE = "inconclusive"
    NOT_COMPARED = "not_compared"


@dataclass
class QuantityComparison:
    quantity: str
    status: AgreementStatus
    method: str                 # weakest deciding method over the components
    components: int = 0
    agreeing: int = 0
    disagreeing: int = 0
    inconclusive: int = 0
    exact: bool = False         # every component decided by exact symbolic means
    residual: float | None = None
    detail: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class CrossBackendComparison:
    metric_name: str
    backend_a: str
    backend_b: str
    independence: str
    quantities: list[QuantityComparison] = field(default_factory=list)
    status: AgreementStatus = AgreementStatus.NOT_COMPARED
    exact: bool = False
    epistemic_note: str = ""
    seed: int = DEFAULT_SEED

    @property
    def compared(self) -> list[QuantityComparison]:
        """Quantities both backends actually produced.

        A quantity one backend deferred (e.g. Kretschmann on warp metrics) is
        ``not_compared``: it contributes no evidence, and it is neither
        counted as agreement nor allowed to look like disagreement.
        """
        return [q for q in self.quantities
                if q.status is not AgreementStatus.NOT_COMPARED]

    @property
    def independently_verified(self) -> bool:
        """True only when every compared quantity agreed conclusively.

        Deliberately conservative: one inconclusive quantity is enough to
        withhold the flag.
        """
        return (self.status is AgreementStatus.AGREE
                and bool(self.compared)
                and all(q.status is AgreementStatus.AGREE for q in self.compared))

    @property
    def disagreements(self) -> list[QuantityComparison]:
        return [q for q in self.quantities if q.status is AgreementStatus.DISAGREE]

    def to_dict(self) -> dict:
        return {
            "metric_name": self.metric_name,
            "backend_a": self.backend_a,
            "backend_b": self.backend_b,
            "independence": self.independence,
            "status": self.status.value,
            "exact": self.exact,
            "independently_verified": self.independently_verified,
            "epistemic_note": self.epistemic_note,
            "seed": self.seed,
            "quantities": [q.to_dict() for q in self.quantities],
        }


def _as_components(value) -> list[tuple[str, sp.Expr]]:
    """Flatten a scalar / Matrix / nested list into labelled components."""
    if value is None:
        return []
    if isinstance(value, sp.MatrixBase):
        n, m = value.shape
        return [(f"[{i},{j}]", value[i, j]) for i in range(n) for j in range(m)]
    if isinstance(value, (list, tuple)):
        out = []

        def walk(node, idx):
            if isinstance(node, (list, tuple)):
                for k, child in enumerate(node):
                    walk(child, idx + [k])
            else:
                out.append(("[" + ",".join(map(str, idx)) + "]", sp.sympify(node)))

        walk(value, [])
        return out
    return [("", sp.sympify(value))]


_METHOD_RANK = {
    EquivalenceMethod.STRUCTURAL: 0,
    EquivalenceMethod.SYMBOLIC_CANCEL: 1,
    EquivalenceMethod.TRIG_ABSTRACTED_SIMPLIFY: 2,
    EquivalenceMethod.SYMBOLIC_SIMPLIFY: 3,
    EquivalenceMethod.NUMERIC_SAMPLING: 4,
    EquivalenceMethod.NONE: 5,
}


def compare_quantity(
    quantity: str,
    value_a,
    value_b,
    **check_kwargs,
) -> QuantityComparison:
    """Compare one tensor/scalar component-by-component."""
    comps_a = _as_components(value_a)
    comps_b = _as_components(value_b)
    if not comps_a or not comps_b:
        return QuantityComparison(
            quantity=quantity, status=AgreementStatus.NOT_COMPARED,
            method=EquivalenceMethod.NONE.value,
            detail="quantity absent from at least one backend",
        )
    if len(comps_a) != len(comps_b):
        return QuantityComparison(
            quantity=quantity, status=AgreementStatus.DISAGREE,
            method=EquivalenceMethod.STRUCTURAL.value,
            components=max(len(comps_a), len(comps_b)),
            disagreeing=abs(len(comps_a) - len(comps_b)),
            detail=f"shape mismatch: backend A has {len(comps_a)} components, "
                   f"backend B has {len(comps_b)}",
        )

    checks: list[tuple[str, EquivalenceCheck]] = []
    for (label, ea), (_, eb) in zip(comps_a, comps_b):
        checks.append((label, check_equivalent(ea, eb, **check_kwargs)))

    agreeing = [c for c in checks if c[1].verdict is Verdict.EQUIVALENT]
    disagreeing = [c for c in checks if c[1].verdict is Verdict.DIFFERENT]
    undecided = [c for c in checks if c[1].verdict is Verdict.INCONCLUSIVE]

    worst_method = max((c[1].method for c in checks),
                       key=lambda m: _METHOD_RANK.get(m, 9))
    residuals = [c[1].residual for c in checks if c[1].residual is not None]
    residual = max(residuals) if residuals else None

    if disagreeing:
        status = AgreementStatus.DISAGREE
        detail = ("backends differ at " + ", ".join(lbl for lbl, _ in disagreeing[:6])
                  + (f" (+{len(disagreeing) - 6} more)" if len(disagreeing) > 6 else "")
                  + "; first: " + disagreeing[0][1].detail)
    elif undecided:
        status = AgreementStatus.INCONCLUSIVE
        detail = ("undecided at " + ", ".join(lbl for lbl, _ in undecided[:6])
                  + (f" (+{len(undecided) - 6} more)" if len(undecided) > 6 else "")
                  + "; first: " + undecided[0][1].detail)
    else:
        status = AgreementStatus.AGREE
        methods = sorted({c[1].method.value for c in checks})
        detail = f"all {len(checks)} components agree (methods: {', '.join(methods)})"

    return QuantityComparison(
        quantity=quantity, status=status, method=worst_method.value,
        components=len(checks), agreeing=len(agreeing),
        disagreeing=len(disagreeing), inconclusive=len(undecided),
        exact=all(c[1].exact for c in checks), residual=residual, detail=detail,
    )


def compare_geometries(
    geometry_a,
    geometry_b,
    *,
    metric_name: str = "",
    backend_a: str = "sympy_coordinate_pipeline",
    backend_b: str = "sympy_orthonormal_frame",
    independence: str = SHARED_CAS_INDEPENDENCE,
    quantities: tuple[str, ...] = DEFAULT_QUANTITIES,
    seed: int = DEFAULT_SEED,
    **check_kwargs,
) -> CrossBackendComparison:
    """Compare two geometry results quantity by quantity."""
    check_kwargs.setdefault("seed", seed)
    record = CrossBackendComparison(
        metric_name=metric_name, backend_a=backend_a, backend_b=backend_b,
        independence=independence, seed=seed,
    )
    for name in quantities:
        va = getattr(geometry_a, name, None)
        vb = getattr(geometry_b, name, None)
        record.quantities.append(compare_quantity(name, va, vb, **check_kwargs))

    compared = record.compared
    if not compared:
        record.status = AgreementStatus.NOT_COMPARED
        record.epistemic_note = (
            "no quantity was comparable between the two backends — this record "
            "is not evidence of anything"
        )
        return record

    if any(q.status is AgreementStatus.DISAGREE for q in compared):
        record.status = AgreementStatus.DISAGREE
        names = ", ".join(q.quantity for q in compared
                          if q.status is AgreementStatus.DISAGREE)
        record.epistemic_note = (
            f"BACKENDS DISAGREE on: {names}. At least one of the two "
            "implementations is wrong; results derived from either must not be "
            "treated as verified until this is resolved."
        )
    elif any(q.status is AgreementStatus.INCONCLUSIVE for q in compared):
        record.status = AgreementStatus.INCONCLUSIVE
        names = ", ".join(q.quantity for q in compared
                          if q.status is AgreementStatus.INCONCLUSIVE)
        record.epistemic_note = (
            f"undecided on: {names}. Neither agreement nor disagreement was "
            "established; this is NOT verification."
        )
    else:
        record.status = AgreementStatus.AGREE
        record.exact = all(q.exact for q in compared)
        strength = ("exact symbolic reduction on every component"
                    if record.exact else
                    "exact symbolic reduction where it terminated, seeded "
                    "numeric sampling elsewhere (see per-quantity methods)")
        record.epistemic_note = (
            f"backends agree on {len(compared)} quantities via {strength}. "
            f"Independence: {independence}"
        )
    return record

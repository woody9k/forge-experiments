"""Cross-backend comparison: agreement, disagreement, and honest silence.

The comparator is the referee between the coordinate pipeline and the
independent frame backend.  A referee that cannot report a disagreement — or
that reports "undecided" as "verified" — is worse than no referee at all, so
those two failure modes are tested as deliberately as the happy path.
"""

import pytest
import sympy as sp

from forge_domain.entities import ValidationStatus
from forge_geometry.entities import MetricDefinition
from forge_metrics.loader import ParsedMetric
from forge_validation.cross_backend import (
    CrossBackendVerification, apply_independent_verification, run_cross_backend_check,
)
from forge_verify import AgreementStatus, compare_geometries, compute_frame_geometry

pytestmark = pytest.mark.validation


class FakeGeometry:
    """Minimal duck-typed geometry — the comparator must not care where the
    numbers came from."""

    def __init__(self, ricci, ricci_scalar=sp.S.Zero):
        self.ricci = ricci
        self.ricci_scalar = ricci_scalar
        self.inverse_metric = sp.eye(2)
        self.einstein = sp.zeros(2, 2)
        self.stress_energy = sp.zeros(2, 2)
        self.kretschmann = None


# --------------------------------------------------------------- agreement

@pytest.mark.parametrize("name", ["minkowski", "schwarzschild"])
def test_backends_agree_on_exact_metrics(geometries, frame_geometries, name):
    pm, geo = geometries(name)
    _, fg = frame_geometries(name)
    rec = compare_geometries(geo, fg, metric_name=name)

    assert rec.status is AgreementStatus.AGREE, rec.epistemic_note
    assert rec.independently_verified
    assert rec.exact, "agreement should be exact symbolic here, not sampled"
    assert {q.quantity for q in rec.compared} >= {
        "inverse_metric", "ricci", "ricci_scalar", "einstein", "stress_energy"}
    for q in rec.compared:
        assert q.method, "every comparison must record the method that decided it"


@pytest.mark.slow
@pytest.mark.parametrize("name", ["alcubierre", "natario"])
def test_backends_agree_on_warp_metrics(geometries, frame_geometries, name):
    """Slow: comparing two unsimplified warp-metric tensor fields component by
    component is tens of seconds of `cancel`."""
    pm, geo = geometries(name)
    _, fg = frame_geometries(name)
    rec = compare_geometries(geo, fg, metric_name=name)
    assert rec.status is AgreementStatus.AGREE, rec.epistemic_note
    assert rec.independently_verified


def test_kretschmann_deferred_by_one_backend_is_not_counted_as_agreement(
        geometries, frame_geometries):
    """Warp metrics defer Kretschmann on the coordinate path.  A quantity
    nobody computed is `not_compared` — never evidence."""
    _, geo = geometries("alcubierre")
    _, fg = frame_geometries("alcubierre")
    rec = compare_geometries(geo, fg, metric_name="alcubierre",
                             quantities=("kretschmann",))
    assert rec.status is AgreementStatus.NOT_COMPARED
    assert not rec.independently_verified
    assert "not evidence" in rec.epistemic_note


# ------------------------------------------------------------ disagreement

def test_deliberate_disagreement_is_reported_loudly():
    x = sp.Symbol("x", positive=True)
    a = FakeGeometry(sp.diag(x, 0), ricci_scalar=x)
    b = FakeGeometry(sp.diag(2 * x, 0), ricci_scalar=2 * x)
    rec = compare_geometries(a, b, metric_name="deliberately-mismatched")

    assert rec.status is AgreementStatus.DISAGREE
    assert not rec.independently_verified
    assert "DISAGREE" in rec.epistemic_note
    assert {q.quantity for q in rec.disagreements} == {"ricci", "ricci_scalar"}
    assert rec.disagreements[0].disagreeing >= 1


def test_disagreement_survives_a_realistic_transcription_error(geometries):
    """The class of bug B-2 exists to catch: one character wrong in g_tt.

    The mistyped metric is not a vacuum solution, so the correct pipeline
    result and the mistyped frame result must be reported as different — not
    as "close enough".
    """
    pm, geo = geometries("schwarzschild")
    r = next(c for c in pm.coords if c.name == "r")
    M = pm.params["M"]
    typo = pm.matrix.copy()
    typo[0, 0] = -(1 - M / r)  # should be −(1 − 2M/r); g_rr left correct
    fg = compute_frame_geometry(typo, pm.coords, signature="-+++",
                                simplify_level="full")
    rec = compare_geometries(geo, fg, metric_name="schwarzschild-with-typo",
                             domains={M: (0.01, 0.1), r: (1.0, 2.0)})
    assert rec.status is AgreementStatus.DISAGREE, rec.epistemic_note
    assert not rec.independently_verified
    assert any(q.quantity == "ricci" for q in rec.disagreements)


def test_shape_mismatch_is_a_disagreement_not_a_crash():
    a = FakeGeometry(sp.zeros(2, 2))
    b = FakeGeometry(sp.zeros(3, 3))
    rec = compare_geometries(a, b, metric_name="shape-mismatch")
    assert rec.status is AgreementStatus.DISAGREE
    assert "shape mismatch" in rec.disagreements[0].detail


# ------------------------------------------------------------ inconclusive

def test_inconclusive_comparison_is_never_reported_as_agreement():
    """Two values a part-per-hundred-million apart: sampling cannot call it
    either way, and the record must say exactly that."""
    x = sp.Symbol("x", positive=True)
    a = FakeGeometry(sp.diag(x, 0))
    b = FakeGeometry(sp.diag(x * (1 + 1e-8), 0))
    rec = compare_geometries(a, b, metric_name="ambiguous")

    assert rec.status is AgreementStatus.INCONCLUSIVE
    assert not rec.independently_verified
    assert "NOT verification" in rec.epistemic_note
    ricci = next(q for q in rec.quantities if q.quantity == "ricci")
    assert ricci.status is AgreementStatus.INCONCLUSIVE
    assert ricci.inconclusive >= 1


# -------------------------------------------------- validation-layer wiring

def test_validation_records_carry_the_flag_only_on_agreement(geometries):
    pm, geo = geometries("minkowski")
    verification = run_cross_backend_check(pm, geo, experiment_id="pytest-xb")

    assert verification.error is None
    assert verification.verified
    summary = next(r for r in verification.results
                   if r.validation_type == "cross_backend.summary")
    assert summary.status is ValidationStatus.PASSED
    assert summary.independently_verified
    assert summary.solver_backend.value == "sympy_tetrad"
    assert all(r.evidence for r in verification.results)

    # Known-answer results get stamped only because the comparison concluded.
    from forge_validation import run_validation_suite
    known = run_validation_suite(pm, geo, experiment_id="pytest-xb")
    assert not any(r.independently_verified for r in known)
    stamped = apply_independent_verification(known, verification)
    assert stamped == len(known)
    assert all(r.independently_verified for r in known)


def test_flag_is_withheld_when_the_comparison_did_not_conclude(geometries):
    pm, geo = geometries("minkowski")
    from forge_validation import run_validation_suite
    known = run_validation_suite(pm, geo, experiment_id="pytest-xb2")

    x = sp.Symbol("x", positive=True)
    rec = compare_geometries(FakeGeometry(sp.diag(x, 0)),
                             FakeGeometry(sp.diag(x * (1 + 1e-8), 0)))
    inconclusive = CrossBackendVerification(comparison=rec)
    assert apply_independent_verification(known, inconclusive) == 0
    assert not any(r.independently_verified for r in known)

    failed = CrossBackendVerification(comparison=None, error="backend exploded")
    assert apply_independent_verification(known, failed) == 0


def test_backend_failure_is_recorded_not_swallowed():
    """A metric the independent backend cannot handle yields a loud
    computation_failed record — and certainly not a verification."""
    t, w, x, y = sp.symbols("t w x y", real=True)
    definition = MetricDefinition(
        name="two-timelike", version="0.0.0", dimensions=4, signature="--++",
        coordinates=["t", "w", "x", "y"],
        metric_components={"g_00": "-1", "g_11": "-1", "g_22": "1", "g_33": "1"},
    )
    parsed = ParsedMetric(definition=definition, coords=[t, w, x, y], params={},
                          matrix=sp.diag(-1, -1, 1, 1))
    verification = run_cross_backend_check(parsed, None, experiment_id="pytest-xb3")

    assert verification.comparison is None
    assert not verification.verified
    assert "signature" in verification.error
    assert verification.results[0].status is ValidationStatus.COMPUTATION_FAILED
    assert not verification.results[0].independently_verified

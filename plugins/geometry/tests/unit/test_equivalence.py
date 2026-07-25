"""The equivalence ladder: it must decide correctly, and say how it decided.

These tests are about epistemic honesty as much as correctness — an
undecided comparison must surface as `inconclusive`, never as agreement.
"""

import sympy as sp

from forge_verify.equivalence import (
    EquivalenceMethod, Verdict, check_equivalent, is_zero,
)

x, y = sp.symbols("x y", real=True)


def test_identical_expressions_decided_structurally():
    check = check_equivalent(x**2 + 1, x**2 + 1)
    assert check.verdict is Verdict.EQUIVALENT
    assert check.method is EquivalenceMethod.STRUCTURAL
    assert check.exact


def test_syntactically_different_but_equal_expressions_agree_exactly():
    a = (x**2 - 1) / (x - 1)
    b = x + 1
    check = check_equivalent(a, b)
    assert check.verdict is Verdict.EQUIVALENT
    assert check.method is EquivalenceMethod.SYMBOLIC_CANCEL
    assert check.exact


def test_trig_identity_needs_simplify_and_is_still_exact():
    check = check_equivalent(sp.sin(x) ** 2 + sp.cos(x) ** 2, 1)
    assert check.verdict is Verdict.EQUIVALENT
    assert check.method is EquivalenceMethod.SYMBOLIC_SIMPLIFY
    assert check.exact


def test_genuinely_different_expressions_are_reported_different():
    check = check_equivalent(x**2, x**3)
    assert check.verdict is Verdict.DIFFERENT
    assert check.residual is not None and check.residual > 0
    assert not check.exact


def test_constant_offset_is_caught_symbolically():
    check = check_equivalent(x + 1, x + sp.Rational(3, 2))
    assert check.verdict is Verdict.DIFFERENT
    assert check.method is EquivalenceMethod.SYMBOLIC_CANCEL


def test_tiny_relative_difference_is_inconclusive_not_agreement():
    """A discrepancy inside the ambiguous band is neither proved nor
    disproved — the ladder must say so rather than round it to agreement."""
    check = check_equivalent(x, x * (1 + 1e-8))
    assert check.verdict is Verdict.INCONCLUSIVE
    assert check.method is EquivalenceMethod.NUMERIC_SAMPLING
    assert "ambiguous band" in check.detail


def test_sampling_can_be_disabled_and_then_reports_inconclusive():
    """With sampling off, an undecidable pair is inconclusive — never equal."""
    hard = sp.Function("f")(x) - sp.Function("f")(x) + sp.exp(sp.log(x + y)) - x - y
    check = check_equivalent(hard + sp.sin(x) * 0 + sp.Symbol("q"),
                             sp.Symbol("q") + sp.tan(x) * sp.cot(x) - 1,
                             allow_sampling=False, op_budget=0)
    assert check.verdict is Verdict.INCONCLUSIVE
    assert check.method is EquivalenceMethod.NONE


def test_is_zero_on_a_nonzero_expression():
    assert is_zero(x - x).verdict is Verdict.EQUIVALENT
    assert is_zero(x + 1).verdict is Verdict.DIFFERENT


def test_simplify_introducing_piecewise_is_declined():
    """CLAUDE.md §7: cancel/simplify dividing by sin(θ) invents degenerate
    polar-axis branches.  Those must not read as a nonzero residual."""
    theta = sp.Symbol("theta", real=True)
    a = sp.sin(theta) ** 2 / sp.sin(theta)
    check = check_equivalent(a, sp.sin(theta))
    assert check.verdict is Verdict.EQUIVALENT
    assert check.exact

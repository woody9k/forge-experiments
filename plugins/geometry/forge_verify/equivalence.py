"""Deciding whether two symbolic expressions are the same expression.

This is the hard part of cross-backend verification, and the part most likely
to lie if written carelessly: two correct expressions are almost never
syntactically equal, ``simplify`` is a heuristic, and "simplify did not reach
zero" is *not* evidence of disagreement.

The decision ladder below is applied in order, and **the rung that decided is
recorded** on every result:

1. ``structural``      — the two expressions are literally the same object.
2. ``symbolic_cancel`` — ``cancel(together(expand(a − b))) == 0``.
3. ``trig_abstracted_simplify`` — ``sin``/``cos`` of each free symbol are
   replaced by fresh *positive* symbols and the difference is simplified.
   This is the project's standard mitigation (CLAUDE.md §7) for ``cancel``
   dividing by ``sin(θ)`` and producing degenerate ``Piecewise`` branches on
   the polar axis.  It is a *weaker* simplifier (it forgets sin²+cos²=1), so
   it can only fail to prove equality, never wrongly prove it; and an
   analytic expression that vanishes on the open set where the abstracted
   symbols are positive vanishes on the whole connected chart.
4. ``symbolic_simplify`` — full ``simplify`` on the difference.
5. ``numeric_sampling`` — both expressions are evaluated at seeded
   pseudo-random points and compared relatively.

Verdicts are three-valued and never collapsed:

* ``equivalent``   — a rung above proved equality.
* ``different``    — the difference reduced to a nonzero *number*, or the two
  expressions differ by more than ``DISAGREE_RTOL`` at sampled points.  This
  is a positive finding, not a fallback.
* ``inconclusive`` — nothing decided.  Notably: sampling landing in the
  ambiguous band between ``rtol`` and ``DISAGREE_RTOL``, too few finite
  samples, or a simplifier that ran out of budget.  **Inconclusive is never
  reported as agreement.**
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import sympy as sp

# Relative tolerance below which sampled values count as equal, and above
# which they count as a genuine disagreement.  Between the two the sampling
# is ambiguous and the verdict is inconclusive.
NUMERIC_RTOL = 1e-9
DISAGREE_RTOL = 1e-6
DEFAULT_SAMPLES = 48
DEFAULT_SEED = 20260724
# Sampling box.  Strictly positive by default so that samples stay inside the
# usual chart domains (r > 0, 0 < θ < π) instead of straddling coordinate
# singularities; callers with Cartesian coordinates should pass their own.
DEFAULT_DOMAIN = (0.31, 1.73)
# Expressions larger than this are not handed to `simplify` — on warp metrics
# that is an unbounded cost, and an unfinished simplify is not evidence.
SIMPLIFY_OP_BUDGET = 4000


class Verdict(StrEnum):
    EQUIVALENT = "equivalent"
    DIFFERENT = "different"
    INCONCLUSIVE = "inconclusive"


class EquivalenceMethod(StrEnum):
    STRUCTURAL = "structural"
    SYMBOLIC_CANCEL = "symbolic_cancel"
    TRIG_ABSTRACTED_SIMPLIFY = "trig_abstracted_simplify"
    SYMBOLIC_SIMPLIFY = "symbolic_simplify"
    NUMERIC_SAMPLING = "numeric_sampling"
    NONE = "none"


EXACT_METHODS = frozenset({
    EquivalenceMethod.STRUCTURAL,
    EquivalenceMethod.SYMBOLIC_CANCEL,
    EquivalenceMethod.TRIG_ABSTRACTED_SIMPLIFY,
    EquivalenceMethod.SYMBOLIC_SIMPLIFY,
})


@dataclass
class EquivalenceCheck:
    verdict: Verdict
    method: EquivalenceMethod
    detail: str = ""
    residual: float | None = None
    samples: int = 0

    @property
    def exact(self) -> bool:
        """True when an exact symbolic rung decided this check."""
        return self.verdict is Verdict.EQUIVALENT and self.method in EXACT_METHODS


def _abstract_trig(expr: sp.Expr) -> sp.Expr:
    """Replace sin(x)/cos(x) by fresh positive symbols (see module docstring)."""
    subs = {}
    for func in expr.atoms(sp.sin, sp.cos):
        subs[func] = sp.Dummy(f"_{func.func.__name__}", positive=True)
    return expr.xreplace(subs) if subs else expr


def _cancel(expr: sp.Expr) -> sp.Expr:
    try:
        return sp.cancel(sp.together(sp.expand(expr)))
    except Exception:
        return expr


def _safe_simplify(expr: sp.Expr, op_budget: int) -> sp.Expr | None:
    """`simplify`, declining when it would be unbounded or degenerate.

    Returns None when the expression is over budget, when simplify raised, or
    when simplify *introduced* ``Piecewise`` branches that were not in the
    input — that output is a statement about coordinate-degenerate loci, not
    about the identity, and treating it as a nonzero residual would produce a
    false disagreement.
    """
    if sp.count_ops(expr) > op_budget:
        return None
    try:
        out = sp.simplify(expr)
    except Exception:
        return None
    if out.has(sp.Piecewise) and not expr.has(sp.Piecewise):
        return None
    if out.has(sp.nan, sp.zoo, sp.oo):
        return None
    return out


def _sample(
    a: sp.Expr,
    b: sp.Expr,
    symbols: list[sp.Symbol],
    domains: dict[sp.Symbol, tuple[float, float]] | None,
    samples: int,
    seed: int,
    rtol: float,
) -> EquivalenceCheck:
    domains = domains or {}
    try:
        fa = sp.lambdify(symbols, a, modules=["numpy"])
        fb = sp.lambdify(symbols, b, modules=["numpy"])
    except Exception as exc:
        return EquivalenceCheck(
            Verdict.INCONCLUSIVE, EquivalenceMethod.NUMERIC_SAMPLING,
            detail=f"expressions could not be lambdified: {exc}")

    rng = np.random.default_rng(seed)
    pts = np.empty((samples, len(symbols)), dtype=np.float64)
    for j, s in enumerate(symbols):
        lo, hi = domains.get(s, DEFAULT_DOMAIN)
        pts[:, j] = rng.uniform(lo, hi, size=samples)

    def _real(fn, point) -> float:
        """Evaluate to a real float, or NaN.

        A complex value means the sample landed outside the real domain of
        the expression (a square root of a negative quantity, say).  It is
        dropped as an unusable point — never silently projected onto its real
        part, which would compare two different numbers.
        """
        try:
            val = complex(fn(*point))
        except Exception:
            return float("nan")
        if abs(val.imag) > 1e-12 * max(abs(val.real), 1.0):
            return float("nan")
        return val.real

    va = [_real(fa, p) for p in pts]
    vb = [_real(fb, p) for p in pts]
    arr_a = np.array(va, dtype=np.float64)
    arr_b = np.array(vb, dtype=np.float64)

    finite = np.isfinite(arr_a) & np.isfinite(arr_b)
    n_finite = int(finite.sum())
    if n_finite < max(4, samples // 2):
        return EquivalenceCheck(
            Verdict.INCONCLUSIVE, EquivalenceMethod.NUMERIC_SAMPLING,
            detail=f"only {n_finite}/{samples} sample points evaluated finitely "
                   "on both backends — no numeric evidence either way",
            samples=n_finite)

    scale = max(float(np.abs(arr_a[finite]).max()),
                float(np.abs(arr_b[finite]).max()), 1e-300)
    resid = float(np.abs(arr_a[finite] - arr_b[finite]).max() / scale)
    detail = (f"max relative deviation {resid:.3e} over {n_finite} seeded "
              f"pseudo-random points (seed {seed})")
    if resid <= rtol:
        return EquivalenceCheck(Verdict.EQUIVALENT, EquivalenceMethod.NUMERIC_SAMPLING,
                                detail=detail, residual=resid, samples=n_finite)
    if resid >= DISAGREE_RTOL:
        return EquivalenceCheck(Verdict.DIFFERENT, EquivalenceMethod.NUMERIC_SAMPLING,
                                detail=detail, residual=resid, samples=n_finite)
    return EquivalenceCheck(
        Verdict.INCONCLUSIVE, EquivalenceMethod.NUMERIC_SAMPLING,
        detail=detail + f" — inside the ambiguous band ({rtol:g}, {DISAGREE_RTOL:g}); "
                        "neither agreement nor disagreement is established",
        residual=resid, samples=n_finite)


def check_equivalent(
    a: sp.Expr,
    b: sp.Expr,
    *,
    domains: dict[sp.Symbol, tuple[float, float]] | None = None,
    samples: int = DEFAULT_SAMPLES,
    seed: int = DEFAULT_SEED,
    rtol: float = NUMERIC_RTOL,
    op_budget: int = SIMPLIFY_OP_BUDGET,
    allow_sampling: bool = True,
) -> EquivalenceCheck:
    """Decide whether ``a`` and ``b`` are the same expression."""
    a, b = sp.sympify(a), sp.sympify(b)
    if a == b:
        return EquivalenceCheck(Verdict.EQUIVALENT, EquivalenceMethod.STRUCTURAL,
                                detail="identical expression trees")

    diff = a - b
    d = _cancel(diff)
    if d == 0:
        return EquivalenceCheck(Verdict.EQUIVALENT, EquivalenceMethod.SYMBOLIC_CANCEL,
                                detail="cancel(together(expand(a − b))) reduced to 0")
    if d.is_number:
        try:
            val = complex(d)
        except (TypeError, ValueError):
            val = None
        if val is not None and abs(val) > 0:
            return EquivalenceCheck(
                Verdict.DIFFERENT, EquivalenceMethod.SYMBOLIC_CANCEL,
                detail=f"difference reduced to the nonzero constant {d}",
                residual=abs(val))

    abstracted = _abstract_trig(d)
    if abstracted is not d:
        s = _safe_simplify(abstracted, op_budget)
        if s is not None and s == 0:
            return EquivalenceCheck(
                Verdict.EQUIVALENT, EquivalenceMethod.TRIG_ABSTRACTED_SIMPLIFY,
                detail="difference vanishes with sin/cos abstracted as free "
                       "positive symbols (avoids degenerate polar-axis branches)")

    s = _safe_simplify(d, op_budget)
    if s is not None and s == 0:
        return EquivalenceCheck(Verdict.EQUIVALENT, EquivalenceMethod.SYMBOLIC_SIMPLIFY,
                                detail="simplify(a − b) reduced to 0")

    if not allow_sampling:
        return EquivalenceCheck(
            Verdict.INCONCLUSIVE, EquivalenceMethod.NONE,
            detail="symbolic reduction did not decide and sampling was disabled")

    symbols = sorted(diff.free_symbols, key=lambda s_: s_.name)
    return _sample(a, b, symbols, domains, samples, seed, rtol)


def is_zero(expr: sp.Expr, **kwargs) -> EquivalenceCheck:
    """Decide whether ``expr`` is identically zero, same ladder and reporting."""
    return check_equivalent(expr, sp.S.Zero, **kwargs)

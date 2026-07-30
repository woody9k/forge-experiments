"""Coframe (tetrad) construction for the independent verification backend.

This module builds an orthonormal coframe ``e^a = e^a_μ dx^μ`` satisfying

    g_{μν} = η_{ab} e^a_μ e^b_ν

together with its dual frame ``E_a = E_a^μ ∂_μ`` (``e^a_μ E_b^μ = δ^a_b``).

Two construction branches, chosen from the declared signature:

* **Riemannian** (all ``+``): upper-triangular Cholesky factor Λ of g,
  ``g = Λᵀ Λ``, so ``e^a = Λ_{aμ} dx^μ``.
* **Lorentzian** (leading ``−``, i.e. coordinate 0 timelike): a 3+1 style
  split.  With ``h_ij = g_ij`` (spatial block), ``β_i = g_{0i}``,
  ``β^i = h^{ij} β_j`` and ``α² = β^i β_i − g_{00}``:

      e^0 = α dt,      e^k = Λ^k_i (dx^i + β^i dt)

  where Λ is the Cholesky factor of h.  The dual frame is written down in
  closed form from the same data — **the inverse metric is never formed by
  inverting the 4×4 metric**, which is one of the ways this path stays
  independent of the coordinate-basis pipeline (and one of the reasons it is
  fast on warp metrics).

Failure policy: the constructed coframe is *verified* against the metric
(``η_ab e^a_μ e^b_ν − g_{μν} ≡ 0``, component by component).  If any residual
does not reduce to zero, ``TetradError`` is raised.  Nothing is coerced.

Branch note (recorded, not hidden): each Cholesky diagonal is a square root,
and we take the positive branch (``powsimp(..., force=True)``) rather than an
``Abs``, whose derivative would drag ``sign()`` terms through every downstream
expression.  A sign flip of a coframe leg is a reflection of the frame — it
changes no curvature quantity converted back to coordinates — and the
reconstruction check above holds for either branch, so this is a choice of
frame orientation and not an assumption about the physics.  It is recorded in
``Coframe.notes``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sympy as sp

# Above this SymPy operation count, `factor` is skipped before taking a square
# root: on warp-metric expressions factoring costs more than it saves.
FACTOR_OP_BUDGET = 200


class TetradError(RuntimeError):
    """The coframe could not be built, or does not reproduce the metric."""


Reduction = str  # "none" | "light" | "full"


def reduce_expr(expr: sp.Expr, level: Reduction) -> sp.Expr:
    """Expression reduction used throughout forge_verify.

    Deliberately *not* the pipeline's helper — same three levels, written
    here, so a change of simplification policy on one side cannot silently
    propagate to the other.

    At ``full`` the result is discarded if ``simplify`` *introduced*
    ``Piecewise`` branches (CLAUDE.md §7: dividing by ``sin θ`` on the polar
    axis, or by ``r`` at the origin, makes ``simplify`` case-split on
    coordinate-degenerate loci and hides an otherwise clean expression).  We
    keep the lighter form rather than carry the branches: declining a
    transformation is not the same as coercing a result.
    """
    if level == "none":
        return expr
    light = sp.cancel(sp.together(expr))
    if level == "light":
        return light
    full = sp.simplify(light)
    if full.has(sp.Piecewise) and not light.has(sp.Piecewise):
        return light
    return full


def positive_root(expr: sp.Expr) -> sp.Expr:
    """√expr on the positive branch of each factor (see module docstring).

    ``Abs`` is stripped rather than carried: SymPy evaluates ``sqrt(sin(θ)²)``
    to ``Abs(sin θ)``, whose derivative drags ``sign()`` through every
    subsequent expression and makes simplification diverge.  Dropping it picks
    the frame orientation in which each leg points along increasing
    coordinate — a reflection of the frame, which leaves every curvature
    quantity in coordinates unchanged, and the coframe is verified against the
    metric afterwards either way.
    """
    e = sp.cancel(expr)
    if sp.count_ops(e) <= FACTOR_OP_BUDGET:
        e = sp.factor(e)
    root = sp.powsimp(sp.sqrt(e), force=True)
    return root.replace(sp.Abs, lambda arg: arg)


@dataclass
class Coframe:
    """Orthonormal coframe and its dual frame.

    ``coframe[a, mu]`` is e^a_μ; ``frame[mu, a]`` is E_a^μ; ``eta`` is the
    diagonal frame metric.
    """

    coords: list[sp.Symbol]
    signature: list[int]
    coframe: sp.Matrix
    frame: sp.Matrix
    eta: sp.Matrix
    notes: list[str] = field(default_factory=list)

    @property
    def dim(self) -> int:
        return len(self.coords)

    def inverse_metric(self, level: Reduction = "light") -> sp.Matrix:
        """g^{μν} = η^{ab} E_a^μ E_b^ν — built from the frame, never by
        inverting the metric matrix."""
        n = self.dim
        out = sp.zeros(n, n)
        for mu in range(n):
            for nu in range(mu, n):
                val = reduce_expr(
                    sum(self.signature[a] * self.frame[mu, a] * self.frame[nu, a]
                        for a in range(n)),
                    level,
                )
                out[mu, nu] = val
                out[nu, mu] = val
        return out


def _cholesky_upper(h: sp.Matrix, level: Reduction) -> sp.Matrix:
    """Upper-triangular Λ with h = Λᵀ Λ, for positive-definite symbolic h."""
    n = h.shape[0]
    lam = sp.zeros(n, n)
    for i in range(n):
        pivot = reduce_expr(h[i, i] - sum(lam[k, i] ** 2 for k in range(i)), level)
        if pivot == 0:
            raise TetradError(
                f"Cholesky pivot {i} is identically zero — the spatial block is "
                "degenerate at this order; no orthonormal coframe exists"
            )
        if pivot.is_negative:  # decidable cases only; symbolic ones stay open
            raise TetradError(
                f"Cholesky pivot {i} is negative ({pivot}) — the block is not "
                "positive definite, so this signature has no real orthonormal "
                "coframe; refusing to continue with an imaginary frame leg"
            )
        lam[i, i] = positive_root(pivot)
        for j in range(i + 1, n):
            lam[i, j] = reduce_expr(
                (h[i, j] - sum(lam[k, i] * lam[k, j] for k in range(i))) / lam[i, i],
                level,
            )
    return lam


def _invert_upper(lam: sp.Matrix, level: Reduction) -> sp.Matrix:
    """Inverse of an upper-triangular matrix by back substitution."""
    n = lam.shape[0]
    inv = sp.zeros(n, n)
    for j in range(n - 1, -1, -1):
        inv[j, j] = reduce_expr(1 / lam[j, j], level)
        for i in range(j - 1, -1, -1):
            inv[i, j] = reduce_expr(
                -sum(lam[i, k] * inv[k, j] for k in range(i + 1, j + 1)) / lam[i, i],
                level,
            )
    return inv


def build_coframe(
    g: sp.Matrix,
    coords: list[sp.Symbol],
    signature: str | list[int] = "-+++",
    level: Reduction = "light",
    verify: bool = True,
) -> Coframe:
    n = len(coords)
    if g.shape != (n, n):
        raise TetradError(f"metric shape {g.shape} does not match {n} coordinates")
    sig = _parse_signature(signature, n)
    notes: list[str] = []

    if all(s == 1 for s in sig):
        lam = _cholesky_upper(g, level)
        cof = lam
        fr = _invert_upper(lam, level)  # frame[mu, a] = (Λ^{-1})[mu, a]
        notes.append("Riemannian branch: Cholesky coframe g = Λᵀ Λ")
    elif sig[0] == -1 and all(s == 1 for s in sig[1:]):
        cof, fr, adm_notes = _lorentzian_coframe(g, n, level)
        notes.extend(adm_notes)
    else:
        raise TetradError(
            f"unsupported signature {signature!r}: forge_verify handles "
            "all-plus or leading-minus (one timelike coordinate) signatures"
        )

    notes.append(
        "square roots taken on the positive branch (frame orientation choice; "
        "curvature in coordinates is invariant under a coframe sign flip)"
    )
    eta = sp.diag(*sig)
    cf = Coframe(coords=coords, signature=sig, coframe=cof, frame=fr, eta=eta, notes=notes)
    if verify:
        _verify(cf, g, level)
    return cf


def _parse_signature(signature: str | list[int], n: int) -> list[int]:
    if isinstance(signature, str):
        if set(signature) - {"+", "-"}:
            raise TetradError(f"signature must contain only '+'/'-', got {signature!r}")
        sig = [1 if c == "+" else -1 for c in signature]
    else:
        sig = list(signature)
        if set(sig) - {1, -1}:
            raise TetradError(f"signature entries must be ±1, got {sig!r}")
    if len(sig) != n:
        raise TetradError(f"signature length {len(sig)} does not match {n} coordinates")
    return sig


def _lorentzian_coframe(g: sp.Matrix, n: int, level: Reduction):
    """3+1 split coframe: e^0 = α dt, e^k = Λ^k_i (dx^i + β^i dt)."""
    notes = ["Lorentzian branch: 3+1 split coframe e⁰ = α dt, eᵏ = Λᵏ_i(dxⁱ + βⁱ dt)"]
    h = g[1:, 1:]
    det_h = reduce_expr(h.det(), level)
    if det_h == 0:
        raise TetradError("spatial block determinant is identically zero")
    h_inv = h.adjugate().applyfunc(lambda e: sp.cancel(e / det_h))
    beta_lo = sp.Matrix([g[0, i] for i in range(1, n)])
    beta_up = (h_inv * beta_lo).applyfunc(lambda e: reduce_expr(e, level))
    alpha_sq = reduce_expr((beta_up.T * beta_lo)[0, 0] - g[0, 0], level)
    if alpha_sq == 0:
        raise TetradError(
            "lapse α² is identically zero — coordinate 0 is not timelike here; "
            "no 3+1 orthonormal coframe exists"
        )
    alpha = positive_root(alpha_sq)

    lam = _cholesky_upper(h, level)
    lam_inv = _invert_upper(lam, level)

    cof = sp.zeros(n, n)
    cof[0, 0] = alpha
    for k in range(1, n):
        cof[k, 0] = reduce_expr(
            sum(lam[k - 1, i] * beta_up[i] for i in range(n - 1)), level)
        for j in range(1, n):
            cof[k, j] = lam[k - 1, j - 1]

    # Dual frame in closed form: E_0 = (1/α)(∂_t − β^i ∂_i)  (the Eulerian
    # normal), E_k = (Λ^{-1})^i_k ∂_i.
    fr = sp.zeros(n, n)
    fr[0, 0] = reduce_expr(1 / alpha, level)
    for i in range(1, n):
        fr[i, 0] = reduce_expr(-beta_up[i - 1] / alpha, level)
    for k in range(1, n):
        for i in range(1, n):
            fr[i, k] = lam_inv[i - 1, k - 1]
    return cof, fr, notes


def _verify(cf: Coframe, g: sp.Matrix, level: Reduction) -> None:
    """η_ab e^a_μ e^b_ν must equal g_{μν} exactly, and e^a_μ E_b^μ = δ^a_b.

    This is the load-bearing self-check of the whole independent path: if the
    coframe does not reconstruct the metric, every curvature quantity derived
    from it is meaningless.  An *undecided* residual is a failure too — the
    frame would be unverified, and an unverified frame must not be used as
    independent evidence.
    """
    from forge_verify.equivalence import Verdict, is_zero  # local: avoids cycle

    n = cf.dim
    for mu in range(n):
        for nu in range(mu, n):
            resid = sum(cf.signature[a] * cf.coframe[a, mu] * cf.coframe[a, nu]
                        for a in range(n)) - g[mu, nu]
            check = is_zero(resid)
            if check.verdict is not Verdict.EQUIVALENT:
                raise TetradError(
                    f"coframe does not reproduce the metric at ({mu},{nu}): "
                    f"{check.verdict.value} via {check.method.value} — {check.detail}"
                )
    for a in range(n):
        for b in range(n):
            resid = sum(cf.coframe[a, mu] * cf.frame[mu, b]
                        for mu in range(n)) - (1 if a == b else 0)
            check = is_zero(resid)
            if check.verdict is not Verdict.EQUIVALENT:
                raise TetradError(
                    f"frame is not dual to the coframe at ({a},{b}): "
                    f"{check.verdict.value} via {check.method.value} — {check.detail}"
                )

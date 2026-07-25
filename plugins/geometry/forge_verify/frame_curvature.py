"""Independent curvature computation via an orthonormal frame.

This is the second symbolic path required by backlog item B-2.  It computes
the same physics as ``forge_math.pipeline`` by a **different derivation
route**, and shares no computation code with it.

Route (Cartan / moving-frame):

1. Build an orthonormal coframe e^a and dual frame E_a (``forge_verify.tetrad``).
   Everything downstream uses the *frame*, not the coordinate basis; the
   coordinate inverse metric is never formed by inverting g.
2. Anholonomy (structure) coefficients from the exterior derivative of the
   coframe — ``de^c = −½ C^c_{ab} e^a ∧ e^b``, i.e.

       C^c_{ab} = E_a^μ E_b^ν (∂_ν e^c_μ − ∂_μ e^c_ν)

3. Ricci rotation coefficients from the Koszul formula in a frame where the
   frame metric η is constant (so all three ``X g(Y,Z)`` terms drop):

       Γ_{abc} = ½ (C_{abc} − C_{bca} − C_{cba}),   Γ^a_{bc} = η^{ad} Γ_{dbc}

   (indices moved with η, not with g).  Metric compatibility shows up as
   Γ_{abc} = −Γ_{cba}, which is checked, not assumed.
4. Curvature from the second structure equation in components — the extra
   ``C`` term is the price of a non-coordinate basis:

       R^a_{bcd} = E_c(Γ^a_{db}) − E_d(Γ^a_{cb})
                   + Γ^a_{ce} Γ^e_{db} − Γ^a_{de} Γ^e_{cb} − C^e_{cd} Γ^a_{eb}

5. Ricci R_{bd} = R^a_{bad}; scalar R = η^{bd} R_{bd}; Einstein
   G_{ab} = R_{ab} − ½ R η_{ab}; stress-energy T_{ab} = G_{ab}/(8π)
   (geometrized, G = c = 1).  Kretschmann is a plain signed sum of squares in
   an orthonormal frame — no four-fold inverse-metric contraction.
6. Frame results are pushed back to coordinates with the coframe:
   R_{μν} = e^a_μ e^b_ν R_{ab}, and likewise for G and T.

Conventions match the coordinate pipeline (MTW; R(E_c,E_d)E_b = R^a_{bcd}E_a),
because the point of the exercise is to compare numbers — but every formula
above is derived and implemented here independently.

**Honest scope of the independence** (see docs/validation-report.md): this is
an independent *implementation and derivation route* running on the *same
computer-algebra system*.  It catches index, sign, convention, algebra and
transcription errors in either path.  It cannot catch a bug in SymPy itself,
since both paths would inherit it.

Failure policy: no stage substitutes a default.  A degenerate frame, a
non-antisymmetric rotation coefficient, or an unreducible residual raises
``FrameGeometryError``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import sympy as sp

from forge_verify.equivalence import Verdict, is_zero
from forge_verify.tetrad import Coframe, TetradError, build_coframe, reduce_expr

Reduction = str  # "none" | "light" | "full"


class FrameGeometryError(RuntimeError):
    """A stage of the frame curvature computation failed."""


@dataclass
class FrameGeometry:
    """Curvature computed on the frame route, in both frame and coordinates."""

    coords: list[sp.Symbol]
    coframe: Coframe
    metric: sp.Matrix
    inverse_metric: sp.Matrix
    anholonomy: list          # C[a][b][c] = C^a_{bc}
    rotation: list            # Γ[a][b][c] = Γ^a_{bc}   (frame indices)
    riemann_frame: list       # R[a][b][c][d] = R^a_{bcd} (frame indices)
    ricci_frame: sp.Matrix
    ricci_scalar: sp.Expr
    einstein_frame: sp.Matrix
    stress_energy_frame: sp.Matrix
    ricci: sp.Matrix          # coordinate components
    einstein: sp.Matrix
    stress_energy: sp.Matrix
    kretschmann: sp.Expr | None
    simplify_level: Reduction
    warnings: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)

    @property
    def dim(self) -> int:
        return len(self.coords)

    def eulerian_energy_density(self, level: Reduction = "light") -> sp.Expr:
        """ρ = T_{ab} n^a n^b for the Eulerian observer.

        In the 3+1 coframe the Eulerian normal *is* the timelike frame leg
        E_0, so this is simply the frame component T_{00} — no observer
        four-vector has to be reconstructed from the inverse metric.
        """
        if self.coframe.signature[0] != -1:
            raise FrameGeometryError(
                "Eulerian energy density requires a Lorentzian frame with a "
                "timelike leg 0"
            )
        return reduce_expr(self.stress_energy_frame[0, 0], level)


def compute_frame_geometry(
    g: sp.Matrix,
    coords: list[sp.Symbol],
    signature: str | list[int] = "-+++",
    simplify_level: Reduction = "light",
    compute_kretschmann: bool = False,
    to_coordinates: bool = True,
) -> FrameGeometry:
    """Curvature of ``g`` by the orthonormal-frame route.

    ``to_coordinates=False`` skips the (expensive) push-back of the frame
    tensors to coordinate components; the coordinate fields are then left as
    empty matrices and only the frame quantities are populated.  Use it when
    the caller only needs frame-basis results (e.g. the Eulerian energy
    density, which is a frame component).
    """
    n = len(coords)
    if g.shape != (n, n):
        raise FrameGeometryError(f"metric shape {g.shape} does not match {n} coordinates")
    asym = (g - g.T).applyfunc(lambda e: sp.cancel(sp.together(e)))
    if any(e != 0 for e in asym):
        raise FrameGeometryError("metric tensor is not symmetric")

    warnings: list[str] = []
    timings: dict[str, float] = {}
    lvl = simplify_level

    t0 = time.monotonic()
    try:
        cf = build_coframe(g, coords, signature=signature, level=lvl)
    except TetradError as exc:
        raise FrameGeometryError(f"coframe construction failed: {exc}") from exc
    timings["coframe"] = time.monotonic() - t0
    warnings.extend(f"tetrad: {note}" for note in cf.notes)

    sig = cf.signature
    e, E = cf.coframe, cf.frame

    def dirderiv(expr: sp.Expr, a: int) -> sp.Expr:
        """E_a(f) = E_a^μ ∂_μ f."""
        return sum(E[mu, a] * sp.diff(expr, coords[mu]) for mu in range(n)
                   if E[mu, a] != 0)

    # ---- anholonomy coefficients C^c_{ab} (antisymmetric in a, b) ----------
    t0 = time.monotonic()
    de = [[[sp.diff(e[c, mu], coords[nu]) - sp.diff(e[c, nu], coords[mu])
            for nu in range(n)] for mu in range(n)] for c in range(n)]
    C = [[[sp.S.Zero] * n for _ in range(n)] for _ in range(n)]
    for c in range(n):
        for a in range(n):
            for b in range(a + 1, n):
                val = reduce_expr(
                    sum(E[mu, a] * E[nu, b] * de[c][mu][nu]
                        for mu in range(n) for nu in range(n)
                        if de[c][mu][nu] != 0),
                    lvl,
                )
                C[c][a][b] = val
                C[c][b][a] = -val
    timings["anholonomy"] = time.monotonic() - t0

    # ---- Ricci rotation coefficients Γ^a_{bc} -----------------------------
    t0 = time.monotonic()
    C_low = [[[sig[a] * C[a][b][c] for c in range(n)] for b in range(n)] for a in range(n)]
    gamma_low = [[[sp.S.Zero] * n for _ in range(n)] for _ in range(n)]
    for a in range(n):
        for b in range(n):
            for c in range(n):
                gamma_low[a][b][c] = reduce_expr(
                    (C_low[a][b][c] - C_low[b][c][a] - C_low[c][b][a]) / 2, lvl)
    # Metric compatibility check: Γ_{abc} = −Γ_{cba}.  Derived, so verified —
    # a violation means the frame is not orthonormal or the connection is not
    # metric, and nothing downstream would be trustworthy.
    for a in range(n):
        for b in range(n):
            for c in range(a + 1, n):
                check = is_zero(gamma_low[a][b][c] + gamma_low[c][b][a])
                if check.verdict is Verdict.DIFFERENT:
                    raise FrameGeometryError(
                        f"rotation coefficients are not antisymmetric in (a,c) at "
                        f"({a},{b},{c}): {check.detail} — the frame is not "
                        "orthonormal or the connection is not metric"
                    )
                if check.verdict is Verdict.INCONCLUSIVE:
                    warnings.append(
                        f"metric-compatibility check Γ_{{{a}{b}{c}}} = −Γ_{{{c}{b}{a}}} "
                        f"undecided: {check.detail}"
                    )
    gamma = [[[reduce_expr(sig[a] * gamma_low[a][b][c], lvl) for c in range(n)]
              for b in range(n)] for a in range(n)]
    timings["rotation"] = time.monotonic() - t0

    # ---- Riemann R^a_{bcd} ------------------------------------------------
    t0 = time.monotonic()
    riemann = [[[[sp.S.Zero] * n for _ in range(n)] for _ in range(n)] for _ in range(n)]
    for a in range(n):
        for b in range(n):
            for c in range(n):
                for d in range(c + 1, n):
                    expr = (
                        dirderiv(gamma[a][d][b], c)
                        - dirderiv(gamma[a][c][b], d)
                        + sum(gamma[a][c][x] * gamma[x][d][b]
                              - gamma[a][d][x] * gamma[x][c][b] for x in range(n))
                        - sum(C[x][c][d] * gamma[a][x][b] for x in range(n))
                    )
                    expr = reduce_expr(expr, lvl)
                    riemann[a][b][c][d] = expr
                    riemann[a][b][d][c] = -expr
    timings["riemann"] = time.monotonic() - t0

    # ---- Ricci, scalar, Einstein, stress-energy (frame indices) -----------
    t0 = time.monotonic()
    ricci_f = sp.zeros(n, n)
    for b in range(n):
        for d in range(b, n):
            val = reduce_expr(sum(riemann[a][b][a][d] for a in range(n)), lvl)
            ricci_f[b, d] = val
            ricci_f[d, b] = val
    ricci_scalar = reduce_expr(sum(sig[b] * ricci_f[b, b] for b in range(n)), lvl)
    einstein_f = sp.zeros(n, n)
    for a in range(n):
        for b in range(a, n):
            val = reduce_expr(
                ricci_f[a, b] - ricci_scalar * (sig[a] if a == b else 0) / 2, lvl)
            einstein_f[a, b] = val
            einstein_f[b, a] = val
    stress_f = einstein_f.applyfunc(lambda x: reduce_expr(x / (8 * sp.pi), lvl))
    timings["ricci_einstein"] = time.monotonic() - t0

    # ---- push back to coordinates ----------------------------------------
    t0 = time.monotonic()
    def to_coords(m: sp.Matrix) -> sp.Matrix:
        out = sp.zeros(n, n)
        for mu in range(n):
            for nu in range(mu, n):
                val = reduce_expr(
                    sum(e[a, mu] * e[b, nu] * m[a, b]
                        for a in range(n) for b in range(n) if m[a, b] != 0),
                    lvl,
                )
                out[mu, nu] = val
                out[nu, mu] = val
        return out

    if to_coordinates:
        ricci_c = to_coords(ricci_f)
        einstein_c = to_coords(einstein_f)
        stress_c = to_coords(stress_f)
        g_inv = cf.inverse_metric(lvl)
    else:
        ricci_c = einstein_c = stress_c = g_inv = sp.zeros(0, 0)
        warnings.append(
            "coordinate components not computed (to_coordinates=False); only "
            "frame-basis quantities are populated"
        )
    timings["coordinate_transform"] = time.monotonic() - t0

    kret = None
    if compute_kretschmann:
        t0 = time.monotonic()
        try:
            kret = _kretschmann_frame(riemann, sig, n, lvl)
        except Exception as exc:  # surfaced as a warning, never swallowed
            warnings.append(f"frame Kretschmann computation failed: {exc}")
        timings["kretschmann"] = time.monotonic() - t0

    return FrameGeometry(
        coords=coords, coframe=cf, metric=g, inverse_metric=g_inv,
        anholonomy=C, rotation=gamma, riemann_frame=riemann,
        ricci_frame=ricci_f, ricci_scalar=ricci_scalar,
        einstein_frame=einstein_f, stress_energy_frame=stress_f,
        ricci=ricci_c, einstein=einstein_c, stress_energy=stress_c,
        kretschmann=kret, simplify_level=lvl,
        warnings=warnings, timings=timings,
    )


def _kretschmann_frame(riemann, sig, n, level: Reduction) -> sp.Expr:
    """K = R_{abcd} R^{abcd}.

    Orthonormal frame ⇒ raising an index multiplies by η^{aa} = ±1, so the
    contraction is a signed sum of squares of the fully-lowered components.
    """
    total = sp.S.Zero
    for a in range(n):
        for b in range(n):
            for c in range(n):
                for d in range(c + 1, n):
                    low = sig[a] * riemann[a][b][c][d]
                    if low == 0:
                        continue
                    # factor 2 restores the (c,d) ↔ (d,c) pair skipped above
                    total += 2 * sig[a] * sig[b] * sig[c] * sig[d] * low ** 2
    return reduce_expr(total, level)

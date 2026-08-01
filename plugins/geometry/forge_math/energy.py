"""Energy integrals of a sampled energy density (backlog B-16, U-4).

"How much negative energy does this metric require?" is the question the whole
search exists to answer, and it has no single right answer — which is why
backlog U-4 asks it of a human rather than assuming one. Three measures are
defensible and they disagree:

* **coordinate** — :math:`\\int \\rho \\, d^n x`. Cheap, chart-dependent, and
  comparable to nothing published. It flatters exactly the metrics we search
  for: strong spatial distortion is what makes the coordinate measure diverge
  from the physical one, so a warp bubble is where it lies most.
* **proper** — :math:`\\int \\rho \\sqrt{\\det{}^{(3)}g} \\, d^n x`. What
  Alcubierre (1994), Pfenning–Ford and Bobrick–Martire quote, so it is the
  one that can be checked against the literature.
* **ADM** — asymptotic mass rather than a slice integral. The most
  principled notion of *total* energy, and undefined for a spacetime that is
  not asymptotically flat — which includes the comoving Natário form by
  construction (backlog U-3).

So all three are computed and stored side by side, per principle 7: no
aggregate, and the **disagreement between measures is itself a result**. A
metric whose coordinate and proper integrals differ by an order of magnitude
is telling you something about its chart, not about its energy requirement.

Two traps this module refuses to walk into
------------------------------------------

**A 2-D slice integral is not an energy.** Most runs sample a plane
(``x``, ``y`` with ``t``, ``z`` fixed), and integrating over it gives energy
*per unit length* of the suppressed direction, not a total. Reporting that
number as an energy would be wrong by a dimension, and it would look entirely
reasonable next to a published figure. Every result therefore carries the
integration dimension and a unit string, and the 2-D case is labelled
``per_unit_length`` rather than silently promoted.

**ADM is not approximated.** It needs a closed 2-surface in a 3-D spatial
slice, a chart in which asymptotic flatness is even meaningful, and a grid
that actually reaches the far field. When those do not hold the answer is
``available=False`` with the specific reason — never a number. See
``adm_availability`` for what is checked and ``docs/limitations.md`` for
what remains unimplemented.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

#: Measures reported. Order is the order they appear in a score vector.
MEASURES = ("coordinate", "proper", "adm")


class EnergyIntegralError(RuntimeError):
    """An integral could not be computed. Always fatal to that integral —
    it is recorded as unavailable with a reason, never as zero."""


@dataclass(frozen=True)
class EnergyIntegral:
    """One measure's answer, with its own honesty attached.

    ``total`` and ``negative_part`` are ``None`` whenever ``available`` is
    false. There is no sentinel value: a float that means "we could not
    compute this" is the failure mode this platform exists to avoid.
    """

    measure: str
    available: bool
    total: float | None = None
    #: Integral restricted to the region where the density is negative — the
    #: quantity a "how much exotic matter" question is actually asking.
    negative_part: float | None = None
    #: Fraction of sampled points with negative density. Reported separately
    #: because a large negative integral over a tiny region and a small one
    #: over half the grid are different physical situations.
    negative_fraction: float | None = None
    #: 2 for a plane, 3 for a spatial volume.
    dimension: int | None = None
    #: "energy" for a 3-D integral, "energy_per_unit_length" for a plane.
    unit: str = ""
    reason: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return {"measure": self.measure, "available": self.available,
                "total": self.total, "negative_part": self.negative_part,
                "negative_fraction": self.negative_fraction,
                "dimension": self.dimension, "unit": self.unit,
                "reason": self.reason, "warnings": list(self.warnings)}


def _unit_for(dimension: int) -> str:
    """What the number actually is.

    A 3-D spatial integral of an energy density is an energy. A 2-D one is an
    energy per unit length of the direction that was held fixed, and calling
    it an energy is wrong by a dimension in a way that reads as plausible.
    """
    if dimension >= 3:
        return "energy"
    if dimension == 2:
        return "energy_per_unit_length"
    return "energy_per_unit_area"


def _spatial_axes(axes: dict[str, np.ndarray],
                  time_name: str = "t") -> list[str]:
    """The varying coordinates that are not time, in grid order."""
    return [name for name in axes if name != time_name]


def _cell_measure(axes: dict[str, np.ndarray], names: list[str]) -> float:
    """Product of the axis spacings — the coordinate volume of one cell.

    Uniform spacing is assumed and *verified*: ``build_grid`` produces
    ``linspace`` axes, but a non-uniform axis arriving here would make every
    integral silently wrong by a factor that varies across the grid, so it
    raises instead.
    """
    measure = 1.0
    for name in names:
        axis = np.asarray(axes[name], dtype=float)
        if axis.size < 2:
            raise EnergyIntegralError(
                f"axis {name!r} has {axis.size} sample(s); an integral needs "
                f"at least two so a spacing exists")
        steps = np.diff(axis)
        if not np.all(np.isfinite(steps)):
            raise EnergyIntegralError(f"axis {name!r} has non-finite spacing")
        spread = float(np.max(steps) - np.min(steps))
        if spread > 1e-9 * float(np.max(np.abs(steps))):
            raise EnergyIntegralError(
                f"axis {name!r} is not uniformly spaced; this integrator "
                f"assumes a regular grid and would be wrong by a factor that "
                f"varies across it")
        measure *= float(steps[0])
    return measure


def spatial_metric_determinant(metric: np.ndarray, coord_names: list[str],
                               spatial_names: list[str]) -> np.ndarray:
    """``det ³g`` on the grid, from the spatial block of ``g_μν``.

    ``metric`` is the full 4-metric with shape ``(n, n, *grid)``. The spatial
    block is the sub-matrix over the *varying spatial* coordinates — not
    simply "drop index 0", because a run may hold a spatial coordinate fixed
    and the determinant of the sampled plane is what its area element needs.

    Raises on a non-positive determinant: :math:`\\sqrt{\\det{}^{(3)}g}` is a
    volume element, and a chart where it is zero or negative on the sampled
    region is degenerate there. Taking ``abs`` would hide a coordinate
    singularity behind a finite-looking answer.
    """
    idx = [coord_names.index(n) for n in spatial_names]
    block = metric[np.ix_(idx, idx)]              # (k, k, *grid)
    k = len(idx)
    # Move the two matrix axes last so numpy's stacked determinant applies.
    moved = np.moveaxis(np.moveaxis(block, 0, -1), 0, -1)
    det = np.linalg.det(moved)
    if not np.all(np.isfinite(det)):
        bad = float(np.mean(~np.isfinite(det)))
        raise EnergyIntegralError(
            f"the spatial metric determinant is non-finite on {bad:.2%} of "
            f"the grid; the chart is degenerate there and no volume element "
            f"exists")
    if np.any(det <= 0.0):
        bad = float(np.mean(det <= 0.0))
        raise EnergyIntegralError(
            f"det {k}-metric <= 0 on {bad:.2%} of the grid. That is a "
            f"degenerate or signature-flipped chart on the sampled region, "
            f"not a small number: abs() here would turn a coordinate "
            f"singularity into a plausible volume element")
    return det


def coordinate_integral(density: np.ndarray, axes: dict[str, np.ndarray],
                        spatial_names: list[str]) -> EnergyIntegral:
    """:math:`\\int \\rho \\, d^n x` — chart-dependent, comparable to nothing.

    Kept because the *ratio* to the proper integral is diagnostic: it measures
    how much the chart is doing, which is exactly what a warp metric exploits.
    """
    cell = _cell_measure(axes, spatial_names)
    return _summarise("coordinate", density, np.ones_like(density), cell,
                      len(spatial_names))


def proper_integral(density: np.ndarray, metric: np.ndarray,
                    coord_names: list[str], axes: dict[str, np.ndarray],
                    spatial_names: list[str]) -> EnergyIntegral:
    """:math:`\\int \\rho \\sqrt{\\det{}^{(3)}g} \\, d^n x` — the literature's
    measure, and the one whose numbers can be checked against a paper."""
    det = spatial_metric_determinant(metric, coord_names, spatial_names)
    cell = _cell_measure(axes, spatial_names)
    return _summarise("proper", density, np.sqrt(det), cell,
                      len(spatial_names))


def _summarise(measure: str, density: np.ndarray, weight: np.ndarray,
               cell: float, dimension: int) -> EnergyIntegral:
    """Integrate ``density * weight`` and split off the negative region."""
    rho = np.asarray(density, dtype=float)
    if rho.shape != weight.shape:
        raise EnergyIntegralError(
            f"density shape {rho.shape} does not match the volume element's "
            f"{weight.shape}")
    finite = np.isfinite(rho) & np.isfinite(weight)
    warnings: list[str] = []
    if not np.all(finite):
        # Never interpolate or zero-fill: report the fraction and refuse.
        raise EnergyIntegralError(
            f"{float(np.mean(~finite)):.2%} of the sampled density or volume "
            f"element is non-finite; an integral over it would be a number "
            f"with no meaning")

    integrand = rho * weight
    total = float(np.sum(integrand) * cell)
    negative_mask = rho < 0.0
    negative = float(np.sum(integrand[negative_mask]) * cell)
    fraction = float(np.mean(negative_mask))

    if fraction == 0.0:
        warnings.append("no negative energy density on the sampled region — "
                        "either the metric requires none here, or the grid "
                        "does not cover where it does")
    elif fraction > 0.9:
        warnings.append(f"{fraction:.0%} of the grid has negative density; "
                        f"the sampled region is probably inside the "
                        f"structure rather than containing it")
    return EnergyIntegral(
        measure=measure, available=True, total=total, negative_part=negative,
        negative_fraction=fraction, dimension=dimension,
        unit=_unit_for(dimension), warnings=tuple(warnings))


def adm_availability(coord_names: list[str], spatial_names: list[str],
                     metric: np.ndarray | None) -> tuple[bool, str]:
    """Can an ADM mass be defined for this run at all?

    Checked *before* any attempt, because the honest answer for most runs is
    "no" and a number produced anyway would be indistinguishable from one that
    means something. Three requirements, each of which fails loudly:

    1. **A 3-D spatial slice.** ADM is a surface integral over a closed
       2-surface at large radius. A plane has no such boundary; a 2-D run can
       no more have an ADM mass than a line can have a volume.
    2. **A chart where asymptotic flatness is meaningful.** The comoving
       Natário form is non-flat at infinity by construction (backlog U-3), so
       the question is not merely unanswered there but ill-posed.
    3. **A grid that reaches the far field.** Even in 3-D, ADM converges only
       as the boundary recedes; evaluating it on a box that stops inside the
       structure measures the box, not the spacetime.

    Returns ``(False, reason)`` in every case today: the surface integral
    itself is not implemented, and shipping an untested one that no current
    run can even reach would be worse than an honest gate. Tracked as B-16's
    remaining work.
    """
    if len(spatial_names) < 3:
        return False, (
            f"ADM mass needs a closed 2-surface in a 3-D spatial slice; this "
            f"run sampled {len(spatial_names)} spatial dimension(s) "
            f"({', '.join(spatial_names) or 'none'}). A plane has no boundary "
            f"surface to integrate over")
    if metric is None:
        return False, "no metric was evaluated on the grid"
    return False, (
        "the ADM surface integral is not implemented. The gate above is, so "
        "this reports unavailable rather than a number: see backlog B-16 and "
        "U-3 (whether asymptotic-flatness checks should run in the rest "
        "frame) before implementing it")


def energy_integrals(density: np.ndarray, axes: dict[str, np.ndarray],
                     coord_names: list[str],
                     metric: np.ndarray | None = None,
                     time_name: str = "t") -> dict[str, EnergyIntegral]:
    """All three measures, side by side, none of them aggregated.

    A measure that cannot be computed appears as ``available=False`` with the
    reason it could not — the vector always has the same three entries, so a
    consumer can never mistake "missing" for "zero".
    """
    spatial_names = _spatial_axes(axes, time_name)
    out: dict[str, EnergyIntegral] = {}

    for name, fn in (("coordinate",
                      lambda: coordinate_integral(density, axes,
                                                  spatial_names)),
                     ("proper",
                      lambda: proper_integral(density, metric, coord_names,
                                              axes, spatial_names))):
        if name == "proper" and metric is None:
            out[name] = EnergyIntegral(
                measure=name, available=False,
                reason="no metric was evaluated on the grid, so there is no "
                       "volume element")
            continue
        try:
            out[name] = fn()
        except EnergyIntegralError as exc:
            out[name] = EnergyIntegral(measure=name, available=False,
                                       reason=str(exc))

    ok, reason = adm_availability(coord_names, spatial_names, metric)
    out["adm"] = EnergyIntegral(measure="adm", available=ok, reason=reason)
    return out


def chart_sensitivity(integrals: dict[str, EnergyIntegral]) -> float | None:
    """``|proper / coordinate|`` for the negative part — how much of the
    answer is the chart.

    Near 1, the coordinate integral is an honest proxy. Far from 1, it is not,
    and any published comparison must use the proper measure. ``None`` when
    either measure is unavailable or the coordinate integral is zero.
    """
    a, b = integrals.get("coordinate"), integrals.get("proper")
    if not (a and b and a.available and b.available):
        return None
    if not a.negative_part:
        return None
    return abs(b.negative_part / a.negative_part)

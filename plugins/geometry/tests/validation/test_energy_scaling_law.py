"""The Alcubierre exotic-energy scaling law, as a known answer.

Integrating Alcubierre's eq. 19 over the equatorial plane gives a closed
form, and the pipeline reproduces it. Deriving it is short enough to record
here, because a known-answer test whose "known answer" nobody can re-derive
is just a golden file.

On the ``t = 0, z = 0`` slice, eq. 19 is

    rho = -(1/8pi) v^2 (y^2 + z^2)/(4 r_s^2) (df/dr_s)^2
        = -(v^2/32pi) (y^2/r^2) (df/dr)^2                (z = 0, r_s = r)

In plane polars centred on the bubble, ``y^2/r^2 = sin^2(phi)`` and the
angular integral contributes ``pi``:

    integral rho dA = -(v^2/32pi) * pi * integral (df/dr)^2 r dr

For a wall thin compared to the bubble (``sigma R >> 1``) the tanh wall has
``df/dr ~= -(sigma/2) sech^2(sigma (r - R))``, which is sharply peaked at
``r = R``, so ``r`` may be taken outside as ``R``:

    integral (df/dr)^2 r dr ~= (sigma^2/4) R integral sech^4(u) du/sigma
                             = (sigma R/4)(4/3) = sigma R/3

giving

    integral rho dA = -v^2 sigma R / 96

**Units matter and this one is easy to misread.** This is a 2-D slice
integral, so it is an energy *per unit length* of the suppressed ``z``
direction, in geometrized units — not a total energy, and not comparable to
a published total. See ``forge_math.energy`` and limitations 9a.

The law is asymptotic in ``sigma R``, so the tolerance below is tight where
the wall is thin and deliberately looser where it is not. The residual at
``sigma R = 4`` is ~0.13% and shrinks to below 1e-5 by ``sigma R = 6``,
which is the expected ``O(1/(sigma R))`` behaviour rather than numerical
error — asserted as a *trend* in the last test, because a scaling law that
happened to fit at three points and drift at the fourth would otherwise pass.
"""

from __future__ import annotations

import json
import math
import os

import pytest

from forge_geometry.app.runner import execute_experiment
from forge_geometry.entities import Experiment, GridSpec
from forge_metrics import builtin_metrics, load_metric_file

pytestmark = [pytest.mark.validation, pytest.mark.slow]

#: |E_neg| per unit length on the equatorial slice, geometrized units.
COEFFICIENT = 1.0 / 96.0


def scaling_law(velocity: float, radius: float, wall_steepness: float) -> float:
    return -COEFFICIENT * velocity ** 2 * radius * wall_steepness


@pytest.fixture(scope="module")
def definition():
    return load_metric_file(builtin_metrics()["alcubierre"]).definition


@pytest.fixture(scope="module")
def bundle_root(tmp_path_factory):
    previous = os.environ.get("EXPERIMENTS_DIR")
    os.environ["EXPERIMENTS_DIR"] = str(tmp_path_factory.mktemp("scaling"))
    try:
        yield
    finally:
        if previous is None:
            del os.environ["EXPERIMENTS_DIR"]
        else:
            os.environ["EXPERIMENTS_DIR"] = previous


#: Several tests need the same parameter point, and each run costs a full
#: symbolic pipeline (~10 s) that does not depend on the parameter values at
#: all — they are substituted in the numerical phase.
_RUNS: dict[tuple, float] = {}


def _negative_part(definition, velocity, radius, wall_steepness,
                   points_per_wall=8):
    key = (velocity, radius, wall_steepness, points_per_wall)
    if key not in _RUNS:
        _RUNS[key] = _execute(definition, velocity, radius, wall_steepness,
                              points_per_wall)
    return _RUNS[key]


def _execute(definition, velocity, radius, wall_steepness, points_per_wall):
    """Run one experiment on the metric's own scaled window."""
    bounds = definition.default_grid.resolve(
        {"velocity": velocity, "radius": radius,
         "wall_steepness": wall_steepness})
    resolution = {}
    for coordinate, (lo, hi) in bounds.items():
        needed = math.ceil((hi - lo) * wall_steepness * points_per_wall)
        resolution[coordinate] = max(16, min(needed, 512))
    experiment = Experiment(
        metric_name="alcubierre", metric_version=definition.version,
        metric_hash=definition.hash,
        parameter_values={"velocity": velocity, "radius": radius,
                          "wall_steepness": wall_steepness},
        grid=GridSpec(bounds={k: list(v) for k, v in bounds.items()},
                      resolution=resolution,
                      slice_values=dict(definition.default_grid.fix)),
    )
    run, _manifest = execute_experiment(experiment)
    report = json.loads((run.bundle_dir / "energy_integrals.json").read_text())
    return report["integrals"]["proper"]["negative_part"]


# --------------------------------------------------------------- known answer

@pytest.mark.parametrize("velocity,radius,wall_steepness", [
    (0.5, 1.0, 8.0),      # the default run
    (1.0, 1.0, 8.0),      # v^2
    (0.5, 2.0, 8.0),      # linear in R
    (0.5, 1.0, 16.0),     # linear in sigma
    (0.25, 1.5, 12.0),    # all three at once
])
def test_the_integrated_negative_energy_matches_the_closed_form(
        definition, bundle_root, velocity, radius, wall_steepness):
    measured = _negative_part(definition, velocity, radius, wall_steepness)

    assert measured == pytest.approx(
        scaling_law(velocity, radius, wall_steepness), rel=1e-3)


def test_the_law_is_a_product_not_three_separate_fits(definition, bundle_root):
    """Doubling v doubles nothing on its own — the ratios have to compose.

    A pipeline that got each axis right independently but mixed them up
    (say, by applying the volume element once per axis) would pass every
    single-axis check above and fail here.
    """
    base = _negative_part(definition, 0.5, 1.0, 8.0)
    doubled_all = _negative_part(definition, 1.0, 2.0, 16.0)

    # v^2 * R * sigma  ->  4 * 2 * 2 = 16
    assert doubled_all / base == pytest.approx(16.0, rel=1e-3)


def test_the_thin_wall_approximation_improves_as_the_wall_thins(definition,
                                                                bundle_root):
    """The residual is physics, not noise, so it must *shrink* with sigma R.

    Without this, a law that fitted the thin-wall points and drifted at the
    thick-wall end would look like a clean result with one loose tolerance.
    """
    residuals = []
    for wall_steepness in (4.0, 6.0, 10.0):
        measured = _negative_part(definition, 0.5, 1.0, wall_steepness)
        predicted = scaling_law(0.5, 1.0, wall_steepness)
        residuals.append(abs(measured / predicted - 1.0))

    assert residuals == sorted(residuals, reverse=True), residuals
    assert residuals[0] < 2e-3      # sigma R = 4, the thickest wall tested
    assert residuals[-1] < 1e-4     # sigma R = 10


# ------------------------------------------------------- the truncation guard

def test_a_window_that_does_not_follow_the_bubble_under_reports_the_energy(
        definition, bundle_root):
    """Why ``default_grid.scale_with`` exists, as a number rather than a note.

    Before it, every sweep run held ``[-2, 2]²`` however large the bubble
    got. At R = 2 that puts the wall at the grid edge and silently loses
    ~12% of the energy — no warning, no failure, just a smaller number that
    moved the fitted radius exponent.
    """
    scaled = _negative_part(definition, 0.5, 2.0, 8.0)

    truncated_experiment = Experiment(
        metric_name="alcubierre", metric_version=definition.version,
        metric_hash=definition.hash,
        parameter_values={"velocity": 0.5, "radius": 2.0,
                          "wall_steepness": 8.0},
        grid=GridSpec(bounds={"x": [-2.0, 2.0], "y": [-2.0, 2.0]},
                      resolution={"x": 256, "y": 256},
                      slice_values={"t": 0.0, "z": 0.0}),
    )
    run, _ = execute_experiment(truncated_experiment)
    report = json.loads((run.bundle_dir / "energy_integrals.json").read_text())
    truncated = report["integrals"]["proper"]["negative_part"]

    assert scaled == pytest.approx(scaling_law(0.5, 2.0, 8.0), rel=1e-3)
    # The old window loses energy, and enough of it to matter.
    assert abs(truncated) < abs(scaled)
    assert abs(truncated / scaled - 1.0) > 0.10

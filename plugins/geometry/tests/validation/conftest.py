import pytest

from forge_math import compute_geometry
from forge_metrics import builtin_metrics, load_metric_file
from forge_verify import compute_frame_geometry

EXACT_METRICS = ("minkowski", "schwarzschild")


@pytest.fixture(scope="session")
def geometries():
    """Compute each bundled metric's geometry once per test session.

    Simplify levels are chosen per metric: exact metrics get full
    simplification (their checks demand exact zeros); warp metrics run
    unsimplified because their checks are numeric spot-comparisons.
    """
    cache = {}

    def get(name: str):
        if name not in cache:
            pm = load_metric_file(builtin_metrics()[name])
            level = "full" if name in EXACT_METRICS else "none"
            kret = name in EXACT_METRICS
            cache[name] = (pm, compute_geometry(
                pm.matrix, pm.coords, simplify_level=level, compute_kretschmann=kret,
            ))
        return cache[name]

    return get


@pytest.fixture(scope="session")
def frame_geometries():
    """Same metrics, computed by the *independent* frame backend (B-2).

    Simplify levels follow the same policy as the coordinate pipeline: exact
    metrics fully simplified (their checks demand exact zeros), warp metrics
    unsimplified.  The frame route is cheap enough on warp metrics that
    ``none`` still yields expressions the equivalence ladder can decide.
    """
    cache = {}

    def get(name: str):
        if name not in cache:
            pm = load_metric_file(builtin_metrics()[name])
            exact = name in EXACT_METRICS
            cache[name] = (pm, compute_frame_geometry(
                pm.matrix, pm.coords, signature=pm.definition.signature,
                simplify_level="full" if exact else "none",
                compute_kretschmann=exact,
            ))
        return cache[name]

    return get

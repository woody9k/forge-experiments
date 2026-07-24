import pytest

from forge_math import compute_geometry
from forge_metrics import builtin_metrics, load_metric_file


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
            level = "full" if name in ("minkowski", "schwarzschild") else "none"
            kret = name in ("minkowski", "schwarzschild")
            cache[name] = (pm, compute_geometry(
                pm.matrix, pm.coords, simplify_level=level, compute_kretschmann=kret,
            ))
        return cache[name]

    return get

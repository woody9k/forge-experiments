"""Golden-hash regression for the geometry entities and bundled metrics.

Content hashes and spec hashes are provenance-critical: identical specs must
hash identically forever, or every stored bundle and every idempotency check
silently changes meaning. Principle 4 — "same spec ⇒ byte-identical symbolic
artifacts" — is only true as long as these values never move.

The goldens were computed against the **pre-platform-split** entities
(warpforge commit 868b516), before the geometry entities moved out of
`forge_domain` and out of the platform repository entirely. That they still
hold is the evidence that neither move altered provenance.

**If a test here fails, the change altered hash inputs — fix the change, do
not update the golden.** Updating one silently orphans every bundle produced
before it.

History: this file used to be `tests/unit/test_entity_hash_stability.py` in
the platform repo, written for the forge_domain split. It lived on the split
branch and **never made it onto main**, so from the split until 2026-08-01 it
was protecting nothing in either repository while warpforge's CLAUDE.md
claimed golden-hash tests were in place. Found while pruning merged branches.
The `content_hash` half stayed with the platform
(`tests/unit/test_content_hash_stability.py`); the compat-shim assertions
were dropped because those shims are gone by design.
"""

from __future__ import annotations

from forge_geometry.entities import (
    EnergyConditionConfig,
    Experiment,
    GridSpec,
    MetricDefinition,
    ObserverSpec,
    ParameterSpec,
    SolverBackend,
)
from forge_metrics import builtin_metrics, load_metric_file

GOLDEN_METRIC_HASH = (
    "7d2555b5b08428c79e7f00e03ab7363a34a13299bad7e564074cafed6d8bd338")
GOLDEN_SPEC_HASH = (
    "37d91d43f11c428e3a8e5612bb4ef3541100ca54c734798a3e436b66f4ed9d1f")

#: The trusted library. A change here means an existing bundle's
#: `metric_hash` no longer identifies the metric it was produced from.
GOLDEN_BUILTIN_HASHES = {
    "minkowski":
        "f6eab06920f59584b348c0c589bc32098bc260d29fd6d3cd51e9902a0eebc79e",
    "schwarzschild":
        "9180ae2a1f7f4785cc3a473abd8e88352d2c572e7c0c986462c2e0206796da3a",
    "alcubierre":
        "3a039e1556f10eeaec99402b7a15cedd364185af498d4e769832562264f39b32",
    "natario":
        "a6d48682ca5b04a106b881cc48aaa69fb72cdcb826a3374edb5a631bd95058f9",
}


def _golden_metric() -> MetricDefinition:
    return MetricDefinition(
        name="golden-test-metric",
        version="1.0",
        coordinate_system="spherical",
        dimensions=4,
        signature="-+++",
        parameters={
            "M": ParameterSpec(symbol="M", default=1.0, description="mass",
                               minimum=0.0, maximum=10.0)
        },
        coordinates=["t", "r", "theta", "phi"],
        metric_components={
            "g_00": "-(1 - 2*M/r)",
            "g_11": "1/(1 - 2*M/r)",
            "g_22": "r**2",
            "g_33": "r**2*sin(theta)**2",
        },
        assumptions=["r > 2*M"],
    )


def _golden_experiment(md: MetricDefinition) -> Experiment:
    return Experiment(
        metric_name="golden-test-metric",
        metric_version="1.0",
        metric_hash=md.hash,
        parameter_values={"M": 1.0},
        grid=GridSpec(
            bounds={"r": (3.0, 10.0), "theta": (0.1, 3.0)},
            resolution={"r": 16, "theta": 16},
            slice_values={"t": 0.0, "phi": 0.0},
        ),
        energy_conditions=EnergyConditionConfig(
            conditions=["NEC", "WEC"],
            observers=[
                ObserverSpec(kind="eulerian"),
                ObserverSpec(kind="sampled_null", samples=8, seed=3),
            ],
            tolerance=1e-9,
            sample_points=128,
        ),
        solver_backend=SolverBackend.SYMPY,
        random_seed=42,
    )


def test_metric_definition_hash_stable():
    md = _golden_metric()
    assert md.hash == GOLDEN_METRIC_HASH
    assert md.compute_hash() == GOLDEN_METRIC_HASH


def test_experiment_spec_hash_stable():
    exp = _golden_experiment(_golden_metric())
    assert exp.spec_hash() == GOLDEN_SPEC_HASH


def test_spec_hash_ignores_identity_and_timestamps():
    """Two experiments built from the same spec must share a spec hash while
    differing in id — that is what makes a rerun recognisable as a rerun."""
    first = _golden_experiment(_golden_metric())
    second = _golden_experiment(_golden_metric())
    assert second.id != first.id
    assert second.spec_hash() == first.spec_hash()


def test_builtin_metric_hashes_stable():
    found = {name: load_metric_file(path).definition.hash
             for name, path in builtin_metrics().items()
             if name in GOLDEN_BUILTIN_HASHES}
    assert found == GOLDEN_BUILTIN_HASHES


def test_every_golden_metric_is_still_bundled():
    """A golden for a metric that no longer ships is an exemption pretending
    to be coverage."""
    missing = set(GOLDEN_BUILTIN_HASHES) - set(builtin_metrics())
    assert not missing, (
        f"{sorted(missing)} have goldens but are no longer in the trusted "
        f"library — drop the golden, or find out why the metric left")

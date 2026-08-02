"""Spacetime-geometry domain entities.

Moved verbatim from ``forge_domain.entities`` (platform-split Phase 2, PR 2):
these models are geometry vocabulary — metric definitions, coordinate grids,
observer families, energy-condition configuration, the metric experiment and
its results, and warp-candidate scoring — not platform primitives.  They are
destined for the geometry plugin in the Forge Experiments repository.

Field names, ordering, and hash inputs are intentionally byte-identical to
the pre-split definitions; ``tests/unit/test_entity_hash_stability.py`` pins
the golden hashes.  ``forge_domain`` re-exports every name here through a
compat shim until the Phase 5 cleanup, so existing imports keep working.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from forge_domain.entities import (
    ExperimentStatus,
    ResultQuality,
    UnitsMode,
    ValidationStatus,
    content_hash,
    new_id,
    utcnow,
)


class SolverBackend(StrEnum):
    SYMPY = "sympy"
    NUMPY = "numpy"
    JAX = "jax"  # reserved; not shipped in v0.1
    # Independent verification backend (B-2): same CAS, independently derived
    # orthonormal-frame route.  See forge_verify and docs/validation-report.md.
    SYMPY_TETRAD = "sympy_tetrad"


class ParameterSpec(BaseModel):
    symbol: str
    default: float
    description: str = ""
    minimum: float | None = None
    maximum: float | None = None


class DefaultGridSpec(BaseModel):
    """Per-metric default sampling window for the experiment builder.

    ``vary`` maps coordinate name -> suggested (min, max) bounds; ``fix``
    maps every remaining coordinate to a slice value. Together they must
    cover the metric's coordinates exactly (enforced by the loader). This is
    guidance for choosing a physically sensible grid — e.g. the Schwarzschild
    exterior instead of a symmetric window straddling the horizon — not part
    of the metric's physical identity.

    ``scale_with`` maps a *varying* coordinate to the parameter its bounds
    are expressed in units of, so the window follows the structure instead
    of staying where it was written. It is per-axis and opt-in because a
    blanket scaling would be wrong: in a spherical chart ``r`` scales with
    the bubble radius and ``theta`` is an angle that must not.

    This is not cosmetic. A fixed window is a **truncation bug that reports
    a number rather than an error**: the first sweep run on this platform
    held ``[-2, 2]²`` while varying the Alcubierre radius up to 2, so the
    largest bubbles had their wall at the grid edge, several runs reported a
    negative fraction of 1.00, and the fitted radius and wall-steepness
    exponents moved by 25% depending on which truncated runs were excluded.
    The velocity exponent — the one axis nothing truncates — came out at
    Alcubierre's exact 2.0 throughout, which is what made the contrast
    visible.
    """

    vary: dict[str, tuple[float, float]]
    fix: dict[str, float] = Field(default_factory=dict)
    #: coordinate name -> parameter name whose value its bounds are in units
    #: of. A coordinate absent from this map has absolute bounds.
    scale_with: dict[str, str] = Field(default_factory=dict)

    def resolve(self, parameter_values: dict[str, float]
                ) -> dict[str, tuple[float, float]]:
        """Concrete bounds for these parameter values.

        Raises on a non-positive or missing scale, rather than silently
        producing an inverted or collapsed window — either would yield a
        grid that evaluates fine and means nothing.
        """
        out: dict[str, tuple[float, float]] = {}
        for coordinate, (lo, hi) in self.vary.items():
            parameter = self.scale_with.get(coordinate)
            if parameter is None:
                out[coordinate] = (lo, hi)
                continue
            if parameter not in parameter_values:
                raise ValueError(
                    f"default grid scales {coordinate!r} with parameter "
                    f"{parameter!r}, which has no value in {sorted(parameter_values)}")
            scale = float(parameter_values[parameter])
            if not scale > 0.0:
                raise ValueError(
                    f"cannot scale {coordinate!r} by {parameter}={scale}: a "
                    f"non-positive scale inverts or collapses the window")
            out[coordinate] = (lo * scale, hi * scale)
        return out


class MetricDefinition(BaseModel):
    id: str = Field(default_factory=new_id)
    name: str
    version: str
    description: str = ""
    coordinate_system: str = "cartesian"
    dimensions: int = 4
    signature: str = "-+++"
    units_mode: UnitsMode = UnitsMode.GEOMETRIZED
    parameters: dict[str, ParameterSpec] = Field(default_factory=dict)
    coordinates: list[str]
    metric_components: dict[str, str]  # e.g. {"g_00": "-(1 - 2*M/r)"}
    inverse_metric_components: dict[str, str] | None = None  # optional, verified if given
    assumptions: list[str] = Field(default_factory=list)
    # Sampling guidance only — deliberately excluded from compute_hash so
    # adding or tuning defaults never changes a metric's content hash.
    default_grid: DefaultGridSpec | None = None
    source_citation: str = ""
    author: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    hash: str = ""

    @field_validator("signature")
    @classmethod
    def _check_signature(cls, v: str) -> str:
        if set(v) - {"-", "+"}:
            raise ValueError(f"signature must contain only '+' and '-', got {v!r}")
        return v

    def compute_hash(self) -> str:
        return content_hash(
            self.model_dump(
                include={
                    "name", "version", "coordinate_system", "dimensions",
                    "signature", "units_mode", "parameters", "coordinates",
                    "metric_components", "assumptions",
                }
            )
        )

    def model_post_init(self, __context: Any) -> None:
        if not self.hash:
            self.hash = self.compute_hash()


class GridSpec(BaseModel):
    """Coordinate bounds and resolution for numerical evaluation.

    ``bounds`` maps coordinate name -> (min, max). Coordinates absent from
    ``bounds`` are held fixed at ``slice_values[coord]``.
    """

    bounds: dict[str, tuple[float, float]]
    resolution: dict[str, int]
    slice_values: dict[str, float] = Field(default_factory=dict)


class ObserverSpec(BaseModel):
    """Observer families for energy-condition evaluation."""

    kind: str  # "eulerian" | "static" | "user_timelike" | "sampled_timelike" | "sampled_null"
    components: list[str] | None = None  # symbolic components for user_timelike
    samples: int = 16  # for sampled families
    seed: int = 0


class EnergyConditionConfig(BaseModel):
    conditions: list[str] = Field(default_factory=lambda: ["NEC", "WEC", "SEC", "DEC"])
    observers: list[ObserverSpec] = Field(
        default_factory=lambda: [
            ObserverSpec(kind="eulerian"),
            ObserverSpec(kind="sampled_null", samples=16),
            ObserverSpec(kind="sampled_timelike", samples=16),
        ]
    )
    tolerance: float = 1e-9
    sample_points: int = 512


class Experiment(BaseModel):
    id: str = Field(default_factory=new_id)
    metric_name: str
    metric_version: str
    metric_hash: str = ""
    parameter_values: dict[str, float] = Field(default_factory=dict)
    grid: GridSpec | None = None
    solver_backend: SolverBackend = SolverBackend.SYMPY
    precision: str = "float64"
    derivative_method: str = "symbolic"
    observers: list[ObserverSpec] = Field(default_factory=list)
    energy_conditions: EnergyConditionConfig | None = None
    requested_outputs: list[str] = Field(default_factory=list)
    software_version: str = "0.1.0"
    source_commit: str = ""
    container_image_digest: str = ""
    random_seed: int = 0
    status: ExperimentStatus = ExperimentStatus.PENDING
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None

    def spec_hash(self) -> str:
        return content_hash(
            self.model_dump(
                include={
                    "metric_name", "metric_version", "metric_hash",
                    "parameter_values", "grid", "solver_backend", "precision",
                    "derivative_method", "observers", "energy_conditions",
                    "requested_outputs", "random_seed",
                }
            )
        )


class ComputationResult(BaseModel):
    id: str = Field(default_factory=new_id)
    experiment_id: str
    result_type: str  # e.g. "christoffel", "ricci_scalar", "stress_energy", "grid:kretschmann"
    quality: ResultQuality
    tensor_rank: int = 0
    dimensions: list[int] = Field(default_factory=list)
    symbolic_expression: str | None = None  # sympy srepr/str for symbolic results
    array_location: str | None = None  # path inside the experiment bundle for arrays
    units: str = "geometrized"
    precision: str = "exact"
    convergence_status: str = "not_applicable"
    warnings: list[str] = Field(default_factory=list)
    error_estimate: float | None = None
    checksum: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class ValidationResult(BaseModel):
    id: str = Field(default_factory=new_id)
    experiment_id: str
    validation_type: str
    expected: str
    computed: str
    tolerance: float
    status: ValidationStatus
    residual: float | None = None
    evidence: str = ""
    solver_backend: SolverBackend = SolverBackend.SYMPY
    independently_verified: bool = False
    created_at: datetime = Field(default_factory=utcnow)


class CandidateScore(BaseModel):
    """Future-facing scoring record.  Component scores are mandatory —
    an aggregate without its components is not storable."""

    id: str = Field(default_factory=new_id)
    experiment_id: str
    usefulness: float
    negative_energy_penalty: float
    total_energy_penalty: float
    curvature_penalty: float
    tidal_force_penalty: float
    causal_horizon_penalty: float
    instability_penalty: float
    singularity_penalty: float
    novelty: float
    aggregate: float
    scoring_function_version: str
    weights: dict[str, float] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)

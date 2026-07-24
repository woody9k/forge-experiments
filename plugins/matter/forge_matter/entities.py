"""Matter Forge domain entities.

Extends the Metric Forge domain with physically parameterized
configurations. Same contracts as forge_domain: content hashing, explicit
epistemic status on every number, and score vectors that are never reduced
to a single figure of merit.
"""

from __future__ import annotations

from datetime import datetime
from enum import IntEnum, StrEnum
from typing import Any

from pydantic import BaseModel, Field

from forge_domain.entities import content_hash, new_id, utcnow


class ConfidenceLevel(IntEnum):
    """C0–C6 confidence classification (docs/matter-forge-design.md §7).

    The platform itself can never assign C6 (experimentally reproduced),
    and C4 requires cross-validation by an independent solver (backlog B-2).
    """

    C0_INVALID = 0
    C1_EXPLORATORY_PROXY = 1
    C2_SUPPORTED_APPROXIMATION = 2
    C3_CONVERGED_NUMERICAL = 3
    C4_CROSS_VALIDATED = 4
    C5_LITERATURE_BENCHMARKED = 5
    C6_EXPERIMENTALLY_REPRODUCED = 6

    @property
    def label(self) -> str:
        return self.name.replace("_", " ").title()


class ValidationState(StrEnum):
    DRAFT = "draft"                # quarantined; never trusted automatically
    VALIDATED = "validated"        # passed Gate 0 static validation
    REJECTED = "rejected"
    PROMOTED = "promoted"          # reserved for the B-7 promotion workflow


class GateStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    FLAGGED = "flagged"            # passed with warnings requiring review
    NOT_IMPLEMENTED = "not_implemented"
    SKIPPED = "skipped"


class MutationRecord(BaseModel):
    operator: str                  # e.g. "alter_separation"
    operator_version: str
    parameters_before: dict[str, Any]
    parameters_after: dict[str, Any]
    reason: str
    seed: int
    affected_components: list[str]
    applied_at: datetime = Field(default_factory=utcnow)


class MatterConfiguration(BaseModel):
    """The genome plus its identity and lineage metadata.

    `genome` is the schema-validated configuration document verbatim.
    The phenotype is *not* stored here — it is recomputed deterministically
    (and hash-verified) from the genome by the pinned compiler version.
    """

    id: str = Field(default_factory=new_id)
    name: str
    version: str
    description: str = ""
    genome: dict[str, Any]
    genome_hash: str = ""
    compiler_version: str = ""
    phenotype_hash: str = ""       # filled after first successful compile
    parent_ids: list[str] = Field(default_factory=list)
    generation: int = 0
    mutation_history: list[MutationRecord] = Field(default_factory=list)
    validation_state: ValidationState = ValidationState.DRAFT
    created_at: datetime = Field(default_factory=utcnow)

    def compute_genome_hash(self) -> str:
        return content_hash(self.genome)

    def model_post_init(self, __context: Any) -> None:
        if not self.genome_hash:
            self.genome_hash = self.compute_genome_hash()


class EnergyAccount(BaseModel):
    """Five-part energy accounting (design §3). Mandatory wherever any
    locally negative quantity is reported; the warning text is part of the
    record, not a UI afterthought."""

    local_min_energy_density_j_m3: float | None = None
    integrated_vacuum_energy_j: float = 0.0
    apparatus_rest_energy_j: float = 0.0
    support_energy_j: float = 0.0     # rotation, fields, stored energy
    total_system_energy_j: float = 0.0
    vacuum_reference: str = "free_space"
    warning: str = (
        "A locally negative renormalized vacuum-energy density does not "
        "imply that the complete apparatus has negative total mass-energy."
    )


class StressEnergyContribution(BaseModel):
    id: str = Field(default_factory=new_id)
    source_component_id: str
    contribution_type: str         # matter | motion | mechanical | em | vacuum
    tensor_form: str               # human/machine-readable analytic form
    tensor_diag_si_j_m3: list[float] | None = None  # diag(T^0_0…T^3_3) on support
    coordinate_frame: str = "apparatus_rest_frame_cartesian"
    units: str = "SI (J/m^3)"
    geometrized_conversion_factor: float | None = None  # multiply by G/c^4 → 1/m^2
    spatial_support: dict[str, Any] = Field(default_factory=dict)
    approximation: str = ""
    confidence: ConfidenceLevel = ConfidenceLevel.C1_EXPLORATORY_PROXY
    warnings: list[str] = Field(default_factory=list)


class GateReport(BaseModel):
    gate: int
    name: str
    status: GateStatus
    checks: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    duration_s: float = 0.0


class ObservedEffect(BaseModel):
    """A predicted effect at an observation region, with its epistemic
    status attached to the number itself."""

    observation_region_id: str
    effect: str                    # e.g. newtonian_g_m_s2, frame_dragging_rate_rad_s
    value: float | None            # None = not computable here (always paired with C0)
    units: str
    model: str
    confidence: ConfidenceLevel
    warnings: list[str] = Field(default_factory=list)


class ScoreVector(BaseModel):
    """Full score vector — never persisted as an aggregate alone."""

    effect: dict[str, float] = Field(default_factory=dict)
    cost: dict[str, float] = Field(default_factory=dict)
    buildability: dict[str, float] = Field(default_factory=dict)
    safety: dict[str, float] = Field(default_factory=dict)
    confidence_floor: ConfidenceLevel = ConfidenceLevel.C0_INVALID
    novelty: dict[str, float] = Field(default_factory=dict)
    scoring_function_version: str = "matter-0.1.0"


class MatterAnalysis(BaseModel):
    """One evaluation of one configuration through the solver funnel."""

    id: str = Field(default_factory=new_id)
    configuration_id: str
    genome_hash: str
    phenotype_hash: str
    compiler_version: str
    material_db_version: str
    highest_gate_completed: int = -1
    gates: list[GateReport] = Field(default_factory=list)
    contributions: list[StressEnergyContribution] = Field(default_factory=list)
    effects: list[ObservedEffect] = Field(default_factory=list)
    energy_account: EnergyAccount | None = None
    scores: ScoreVector | None = None
    status: str = "pending"        # completed | failed | rejected_gate_<n>
    error: str | None = None
    random_seed: int = 0
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None

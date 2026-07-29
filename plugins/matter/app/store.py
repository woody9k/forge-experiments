"""Matter-domain persistence (platform-split Phase 2).

Rows and accessors moved verbatim from ``apps/coordinator/store.py``; same
ownership rules as ``store_geometry`` — table names and Alembic history are
untouched, and the metadata reaches the platform through the matter plugin
declaration.
"""

from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, Integer, String
from sqlalchemy.orm import DeclarativeBase

from apps.coordinator.store import _finite_json, session


class MatterBase(DeclarativeBase):
    pass


class MatterConfigurationRow(MatterBase):
    __tablename__ = "matter_configurations"
    id = Column(String(64), primary_key=True)
    name = Column(String(64), nullable=False, index=True)
    genome_hash = Column(String(64), nullable=False, index=True)
    phenotype_hash = Column(String(64), nullable=True)
    generation = Column(Integer, nullable=False, default=0)
    parent_ids = Column(JSON, nullable=False, default=list)
    validation_state = Column(String(16), nullable=False, index=True)
    payload = Column(JSON, nullable=False)       # full MatterConfiguration dump
    created_at = Column(DateTime, nullable=False)


class MatterAnalysisRow(MatterBase):
    __tablename__ = "matter_analyses"
    id = Column(String(64), primary_key=True)
    configuration_id = Column(String(64), nullable=False, index=True)
    status = Column(String(32), nullable=False, index=True)
    highest_gate_completed = Column(Integer, nullable=False, default=-1)
    payload = Column(JSON, nullable=False)       # full MatterAnalysis dump
    created_at = Column(DateTime, nullable=False)


# ------------------------------------------------------------- persistence

def save_matter_configuration(config) -> None:
    """Persist a forge_matter MatterConfiguration (pydantic model)."""
    with session() as s:
        s.merge(MatterConfigurationRow(
            id=config.id, name=config.name, genome_hash=config.genome_hash,
            phenotype_hash=config.phenotype_hash or None,
            generation=config.generation, parent_ids=config.parent_ids,
            validation_state=config.validation_state.value,
            payload=_finite_json(config.model_dump(mode="json")),
            created_at=config.created_at.replace(tzinfo=None),
        ))


def load_matter_configuration(config_id: str) -> dict | None:
    with session() as s:
        row = s.get(MatterConfigurationRow, config_id)
        return row.payload if row else None


def list_matter_configurations(limit: int = 100) -> list[dict]:
    with session() as s:
        rows = (s.query(MatterConfigurationRow)
                .order_by(MatterConfigurationRow.created_at.desc())
                .limit(limit).all())
        return [{
            "id": r.id, "name": r.name, "genome_hash": r.genome_hash,
            "generation": r.generation, "parent_ids": r.parent_ids,
            "validation_state": r.validation_state,
            "created_at": r.created_at.isoformat(),
        } for r in rows]


def matter_children(config_id: str) -> list[dict]:
    with session() as s:
        rows = s.query(MatterConfigurationRow).all()
        return [{"id": r.id, "generation": r.generation,
                 "mutations": [m.get("operator") for m in
                               r.payload.get("mutation_history", [])]}
                for r in rows if config_id in (r.parent_ids or [])]


def save_matter_analysis(analysis) -> None:
    with session() as s:
        s.merge(MatterAnalysisRow(
            id=analysis.id, configuration_id=analysis.configuration_id,
            status=analysis.status,
            highest_gate_completed=analysis.highest_gate_completed,
            payload=_finite_json(analysis.model_dump(mode="json")),
            created_at=analysis.created_at.replace(tzinfo=None),
        ))


def load_matter_analysis(analysis_id: str) -> dict | None:
    with session() as s:
        row = s.get(MatterAnalysisRow, analysis_id)
        return row.payload if row else None


def matter_analyses_for(config_id: str) -> list[dict]:
    with session() as s:
        rows = (s.query(MatterAnalysisRow)
                .filter_by(configuration_id=config_id)
                .order_by(MatterAnalysisRow.created_at.desc()).all())
        return [r.payload for r in rows]

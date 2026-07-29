"""Geometry-domain persistence (platform-split Phase 2).

Rows and accessors moved verbatim from ``apps/coordinator/store.py``.  The
tables keep their names and their place in the platform's single Alembic
history — this split changes *code ownership only*, no data or DDL moves.
The metadata is contributed to the platform through the geometry plugin
declaration (``registry.add_persistence_metadata``), which is how the
SQLite dev bootstrap knows to create these tables.
"""

from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase

from apps.coordinator.store import _finite_json, session
from forge_domain.entities import ExperimentStatus
from forge_geometry.entities import ComputationResult, Experiment, ValidationResult


class GeometryBase(DeclarativeBase):
    pass


class MetricRow(GeometryBase):
    __tablename__ = "metrics"
    id = Column(String(64), primary_key=True)
    name = Column(String(64), nullable=False, index=True)
    version = Column(String(32), nullable=False)
    hash = Column(String(64), nullable=False, unique=True, index=True)
    definition = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False)


class ExperimentRow(GeometryBase):
    __tablename__ = "experiments"
    id = Column(String(64), primary_key=True)
    metric_name = Column(String(64), nullable=False, index=True)
    metric_version = Column(String(32), nullable=False)
    metric_hash = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False, index=True)
    spec = Column(JSON, nullable=False)          # full Experiment dump
    spec_hash = Column(String(64), nullable=False, index=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)


class ComputationResultRow(GeometryBase):
    __tablename__ = "computation_results"
    id = Column(String(64), primary_key=True)
    experiment_id = Column(String(64), nullable=False, index=True)
    result_type = Column(String(64), nullable=False)
    quality = Column(String(32), nullable=False)
    payload = Column(JSON, nullable=False)       # full ComputationResult dump
    created_at = Column(DateTime, nullable=False)


class ValidationResultRow(GeometryBase):
    __tablename__ = "validation_results"
    id = Column(String(64), primary_key=True)
    experiment_id = Column(String(64), nullable=False, index=True)
    validation_type = Column(String(96), nullable=False)
    status = Column(String(32), nullable=False, index=True)
    residual = Column(Float, nullable=True)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False)


class CandidateScoreRow(GeometryBase):
    __tablename__ = "candidate_scores"
    id = Column(String(64), primary_key=True)
    experiment_id = Column(String(64), nullable=False, index=True)
    aggregate = Column(Float, nullable=False)
    scoring_function_version = Column(String(32), nullable=False)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False)


# ------------------------------------------------------------- persistence

def save_experiment(exp: Experiment) -> None:
    with session() as s:
        row = s.get(ExperimentRow, exp.id)
        dump = exp.model_dump(mode="json")
        if row is None:
            row = ExperimentRow(id=exp.id, created_at=exp.created_at.replace(tzinfo=None))
            s.add(row)
        row.metric_name = exp.metric_name
        row.metric_version = exp.metric_version
        row.metric_hash = exp.metric_hash
        row.status = exp.status.value
        row.spec = _finite_json(dump)
        row.spec_hash = exp.spec_hash()
        row.error = exp.error
        row.started_at = exp.started_at.replace(tzinfo=None) if exp.started_at else None
        row.completed_at = exp.completed_at.replace(tzinfo=None) if exp.completed_at else None


def save_results(results: list[ComputationResult], validations: list[ValidationResult]) -> None:
    with session() as s:
        for r in results:
            s.merge(ComputationResultRow(
                id=r.id, experiment_id=r.experiment_id, result_type=r.result_type,
                quality=r.quality.value, payload=_finite_json(r.model_dump(mode="json")),
                created_at=r.created_at.replace(tzinfo=None),
            ))
        for v in validations:
            s.merge(ValidationResultRow(
                id=v.id, experiment_id=v.experiment_id,
                validation_type=v.validation_type, status=v.status.value,
                residual=None if v.residual is None or v.residual != v.residual else v.residual,
                payload=_finite_json(v.model_dump(mode="json")),
                created_at=v.created_at.replace(tzinfo=None),
            ))


def load_experiment(experiment_id: str) -> Experiment | None:
    with session() as s:
        row = s.get(ExperimentRow, experiment_id)
        return Experiment.model_validate(row.spec) if row else None


def list_experiments(limit: int = 100) -> list[dict]:
    with session() as s:
        rows = (s.query(ExperimentRow)
                .order_by(ExperimentRow.created_at.desc()).limit(limit).all())
        return [{
            "id": r.id, "metric_name": r.metric_name, "status": r.status,
            "created_at": r.created_at.isoformat(), "error": r.error,
        } for r in rows]


def experiment_validations(experiment_id: str) -> list[dict]:
    with session() as s:
        rows = (s.query(ValidationResultRow)
                .filter_by(experiment_id=experiment_id).all())
        return [r.payload for r in rows]


def experiment_results(experiment_id: str) -> list[dict]:
    with session() as s:
        rows = (s.query(ComputationResultRow)
                .filter_by(experiment_id=experiment_id).all())
        return [r.payload for r in rows]


def update_status(experiment_id: str, status: ExperimentStatus, error: str | None = None) -> None:
    with session() as s:
        row = s.get(ExperimentRow, experiment_id)
        if row:
            row.status = status.value
            if error:
                row.error = error
            spec = dict(row.spec)
            spec["status"] = status.value
            if error:
                spec["error"] = error
            row.spec = spec

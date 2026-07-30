"""Persistence the pendulum plugin owns.

The table is prefixed with the plugin's name: the platform may want generic
names like ``runs`` or ``observations`` for core concepts, and the
conformance harness warns if a plugin squats on one.
"""

from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, Float, String
from sqlalchemy.orm import DeclarativeBase

from apps.coordinator.store import _finite_json, session
from forge_domain.entities import new_id, utcnow


class PendulumBase(DeclarativeBase):
    pass


class PendulumRunRow(PendulumBase):
    __tablename__ = "pendulum_runs"
    id = Column(String(64), primary_key=True)
    length_m = Column(Float, nullable=False)
    initial_angle_deg = Column(Float, nullable=False)
    status = Column(String(16), nullable=False, index=True)
    payload = Column(JSON, nullable=False)      # spec + result + provenance
    created_at = Column(DateTime, nullable=False)


def save_run(run: dict) -> str:
    """Persist one run.  ``_finite_json`` keeps NaN/Inf out of JSON columns —
    PostgreSQL rejects them, and a non-finite number belongs in a quality
    label rather than a float column (platform CLAUDE.md §7)."""
    with session() as s:
        row = s.get(PendulumRunRow, run["id"]) or PendulumRunRow(
            id=run["id"], created_at=utcnow().replace(tzinfo=None))
        row.length_m = run["spec"]["length_m"]
        row.initial_angle_deg = run["spec"]["initial_angle_deg"]
        row.status = run["status"]
        row.payload = _finite_json(run)
        s.merge(row)
    return run["id"]


def load_run(run_id: str) -> dict | None:
    with session() as s:
        row = s.get(PendulumRunRow, run_id)
        return row.payload if row else None


def list_runs(limit: int = 100) -> list[dict]:
    with session() as s:
        rows = (s.query(PendulumRunRow)
                .order_by(PendulumRunRow.created_at.desc()).limit(limit).all())
        return [{"id": r.id, "length_m": r.length_m,
                 "initial_angle_deg": r.initial_angle_deg, "status": r.status,
                 "created_at": r.created_at.isoformat()} for r in rows]


def new_run_id() -> str:
    return new_id()

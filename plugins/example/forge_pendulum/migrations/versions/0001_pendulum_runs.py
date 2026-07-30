"""pendulum_runs

The first migration of the first plugin to own a branch (platform backlog
P-5).  Until this existed, a plugin's tables were created only by the
SQLite dev path's ``create_all``: on PostgreSQL this domain had no schema
at all and every write failed with ``relation "pendulum_runs" does not
exist``.

Revision ID: pendulum0001
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "pendulum0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pendulum_runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("length_m", sa.Float, nullable=False),
        sa.Column("initial_angle_deg", sa.Float, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("pendulum_runs")

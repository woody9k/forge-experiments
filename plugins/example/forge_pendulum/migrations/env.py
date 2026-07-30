"""Pendulum Lab's Alembic environment.

Two lines, because ``forge_sdk.migrations.run_migrations`` handles the part
a plugin must not get wrong: writing this branch's head into the version
table the platform assigned it (``alembic_version_pendulum``) rather than
into ``alembic_version``, which core owns.
"""

from forge_pendulum.app.store import PendulumBase
from forge_sdk.migrations import run_migrations

run_migrations(target_metadata=PendulumBase.metadata)

"""The queue task type this plugin contributes.

Wire names are namespaced (``pendulum.*``): they are queue protocol, shared
with every other plugin on the same broker.
"""

from __future__ import annotations

import logging

from forge_pendulum.app import runner
from forge_sdk import QueueTaskType

log = logging.getLogger("forge.pendulum")


def run_experiment(task, payload) -> dict:
    """Celery handler.  ``task`` is the bound task (request metadata)."""
    spec, run_id = (payload if isinstance(payload, dict)
                    else {"spec": payload, "run_id": None}), None
    # The platform passes through whatever the producer sent; accept both the
    # (spec, run_id) call used by the API and a bare spec.
    if isinstance(payload, dict):
        spec, run_id = payload, None
    run = runner.execute(spec, run_id)
    log.info("pendulum run %s finished: %s", run["id"], run["status"],
             extra={"task_id": task.request.id})
    return {"id": run["id"], "status": run["status"]}


TASK_TYPES = [
    QueueTaskType(name="pendulum.run_experiment", queue="numerical",
                  handler=run_experiment),
]

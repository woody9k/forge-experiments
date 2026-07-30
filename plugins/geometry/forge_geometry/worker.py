"""Geometry's worker-side contribution (platform backlog P-3).

A Worker Fabric agent runs where there is no database and no coordinator, so
it cannot build the plugin registry.  It reads this module through the
``forge.worker`` entry point instead: the self-test suites that prove a host
can be trusted with geometry work, and the executor that runs a geometry
experiment.

Both used to be reached by two literal strings inside the *platform's* agent
(``forge_geometry.selftests`` and ``forge_geometry.app.runner``), which meant
no other domain's jobs could ever run on the fleet.

Keep this module free of ``forge_geometry.app``'s persistence: it must import
on a host that has no database.  ``app.runner`` is safe — it is the pipeline,
not the store — and is imported lazily so that stays visible.
"""

from __future__ import annotations

from forge_geometry.selftests import SUITES  # noqa: F401 — re-exported
from forge_sdk import JobResult

VERSION = "0.4.0"

#: The job type geometry owns. The coordinator puts this on a job; whichever
#: host takes the lease looks it up here.
JOB_TYPE = "metric_experiment"


def run_experiment_job(payload: dict, workdir: str) -> JobResult:
    """Run one geometry experiment to a finished bundle under ``workdir``.

    The agent has already pointed ``EXPERIMENTS_DIR`` at ``workdir``, so the
    pipeline writes where the agent expects; it uploads the result and the
    coordinator re-verifies every checksum before any of it counts.
    """
    from forge_geometry.app.runner import execute_experiment
    from forge_geometry.entities import Experiment

    experiment = Experiment.model_validate(payload["experiment"])
    _run, manifest = execute_experiment(experiment)
    return JobResult(
        bundle_dir=f"{workdir}/{experiment.id}",
        entity_id=experiment.id,
        provenance={
            "solver_versions": manifest["dependency_versions"],
            "validation_summary": manifest["validation_summary"],
        },
    )


JOB_EXECUTORS = {JOB_TYPE: run_experiment_job}

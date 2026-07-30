"""Pendulum Lab's worker-side contribution — the reference implementation
(platform backlog P-3).

A Worker Fabric agent runs where there is no database, no coordinator and no
plugin registry.  It reads this module through the ``forge.worker`` entry
point: the self-test suites that prove a host can be trusted with this
domain's work, and the executor that runs one of its jobs.

The one rule worth stating twice: **this module and everything it imports
must work with no database.**  ``forge_pendulum.app.runner`` is imported
lazily and only for ``run_to_bundle``, which is the store-free half of the
pipeline; importing ``app.store`` here would make every agent need a
database it has no reason to have.

A plugin may contribute suites without an executor (it validates hosts but
submits no fabric jobs), or an executor without suites (its jobs need only
the baseline capability).  This one does both, because it is the worked
example.
"""

from __future__ import annotations

from forge_pendulum.selftests import SUITES  # noqa: F401 — re-exported
from forge_sdk import JobResult

VERSION = "0.1.0"

#: The job type this domain owns.
JOB_TYPE = "pendulum_run"


def run_pendulum_job(payload: dict, workdir: str) -> JobResult:
    """Integrate one pendulum to a finished bundle under ``workdir``.

    The agent has already pointed ``EXPERIMENTS_DIR`` at ``workdir``. What
    comes back is uploaded and re-verified by the coordinator; nothing this
    function reports about its own run is taken on trust.
    """
    from forge_pendulum.app.runner import run_to_bundle

    spec = payload.get("experiment", payload)
    run_id = spec.get("id") or payload.get("run_id")
    if not run_id:
        from forge_domain.entities import new_id
        run_id = new_id()

    run = run_to_bundle(spec.get("spec", spec), run_id)
    if run["status"] != "completed":
        raise RuntimeError(f"pendulum run {run_id} failed: {run['error']}")
    return JobResult(
        bundle_dir=f"{workdir}/{run_id}",
        entity_id=run_id,
        provenance={
            "solver_versions": run["manifest"]["dependency_versions"],
            "validation_summary": run["manifest"]["validation_summary"],
        },
    )


JOB_EXECUTORS = {JOB_TYPE: run_pendulum_job}

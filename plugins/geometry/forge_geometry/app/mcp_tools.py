"""Geometry-side MCP tools (architecture spec §13): metrics and experiments.

Every tool here is a static binding onto the closed registry in
``forge_sage.tools``.  ``warp_forge.experiments.create`` is bound to
``submit_geometry_experiment``, which is now wired (S-4 remainder closed): it
executes through the same ``runner.execute_experiment`` path the REST API
uses, enforces the program's ``allowed_metric_hashes`` allowlist fail-closed,
and is audited through ``call_tool`` like every other tool.  It is the one
write on this surface, so — like the matter writes — it reserves the
experiment id in the idempotency ledger before the side effect rather than
letting a client name it.
"""

from __future__ import annotations

from apps.coordinator import store
import forge_geometry.app.store as gstore
from apps.mcp._core import McpTool, Reservation, registry_tool
from forge_sage import Role

_EXPERIMENT_ID = {"type": "string", "description": "Experiment id."}


def _load_experiment(experiment_id: str) -> dict | None:
    """Replay lookup for the reservation.

    ``store.load_experiment`` returns the entity; the ledger only needs to know
    whether a prior attempt under this key finished, so hand back a plain dict
    like every other reservation loader.
    """

    experiment = gstore.load_experiment(experiment_id)
    return experiment.model_dump(mode="json") if experiment is not None else None


GEOMETRY_TOOLS: tuple[McpTool, ...] = (
    registry_tool(
        "warp_forge.metrics.list",
        tool_name="list_metrics", role=Role.ANALYST,
        title="List trusted metric definitions",
        description=("List the bundled metric definitions with their content "
                     "hashes and whether the program's policy allowlists each."),
    ),
    registry_tool(
        "warp_forge.metrics.get",
        tool_name="get_metric", role=Role.ANALYST,
        title="Fetch one metric definition",
        description="Fetch a single bundled metric definition by name.",
        arguments={"name": {"type": "string",
                            "description": "Metric name, e.g. 'alcubierre'."}},
        required=("name",),
    ),
    registry_tool(
        "warp_forge.experiments.create",
        tool_name="submit_geometry_experiment", role=Role.DESIGNER,
        title="Submit a geometry experiment",
        description=("Submit an approved geometry experiment to Warp Forge. It "
                     "runs through the same pipeline as "
                     "POST /api/v1/experiments. The metric must be on the "
                     "program's allowlist (allowed_metric_hashes) — an empty "
                     "allowlist permits nothing — and the program must be "
                     "ACTIVE with autonomy level 1 or higher. Takes the "
                     "metric's content hash plus optional parameters, grid, "
                     "energy_conditions, and seed. The call is audited, and "
                     "the resulting bundle is re-verified by the coordinator "
                     "before it can support any claim."),
        arguments={
            "metric_hash": {"type": "string",
                            "description": "Content hash of an allowlisted metric."},
            "parameters": {"type": "object",
                           "description": "Metric parameter assignments."},
            "grid": {"type": "object",
                     "description": ("Optional numeric grid specification "
                                     "(GridSpec); omit for the metric default.")},
            "energy_conditions": {
                "type": "object",
                "description": ("Optional energy-condition configuration "
                                "(EnergyConditionConfig); omit for the default.")},
            "seed": {"type": "integer",
                     "description": "Deterministic experiment seed (default 0)."},
        },
        required=("metric_hash",),
        reservation=Reservation(
            argument="experiment_id", object_type="experiment",
            result_key="experiment_id", loader=_load_experiment),
    ),
    registry_tool(
        "warp_forge.experiments.get",
        tool_name="get_experiment", role=Role.ANALYST,
        title="Fetch an experiment record",
        description="Fetch one experiment record by id.",
        arguments={"experiment_id": _EXPERIMENT_ID},
        required=("experiment_id",),
    ),
    registry_tool(
        "warp_forge.experiments.results",
        tool_name="get_experiment_results", role=Role.ANALYST,
        title="Fetch validated experiment results",
        description="Fetch the validated results attached to an experiment.",
        arguments={"experiment_id": _EXPERIMENT_ID},
        required=("experiment_id",),
    ),
    registry_tool(
        "warp_forge.experiments.validations",
        tool_name="get_experiment_validations", role=Role.ANALYST,
        title="Fetch experiment validations",
        description="Fetch the known-answer validation records for an experiment.",
        arguments={"experiment_id": _EXPERIMENT_ID},
        required=("experiment_id",),
    ),
    registry_tool(
        "warp_forge.experiments.compare",
        tool_name="compare_experiments", role=Role.ANALYST,
        title="Compare two experiments",
        description="Compare two experiments' validated observables side by side.",
        arguments={
            "experiment_a": {"type": "string", "description": "First experiment id."},
            "experiment_b": {"type": "string", "description": "Second experiment id."},
        },
        required=("experiment_a", "experiment_b"),
    ),
)

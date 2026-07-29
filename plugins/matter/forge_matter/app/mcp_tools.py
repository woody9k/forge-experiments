"""Matter-side MCP tools (architecture spec §13): configurations and analyses.

``mutate`` and ``simulate`` are the two MCP writes that actually reach Warp
Forge in this phase.  Both reserve the id of the artifact they will create in
the idempotency ledger *before* the side effect, then hand that reserved id to
the same ``sage_tools`` implementation the REST/runtime paths use — the
allowlists (parent configuration, mutation operator, autonomy level) are
evaluated there and fail closed.  ``create`` is bound to the registry's
``create_matter_configuration``, which this phase has not implemented, so it
fails loud.
"""

from __future__ import annotations

from apps.coordinator import store
import forge_matter.app.store as mstore
from apps.mcp._core import McpTool, Reservation, registry_tool
from forge_sage import Role

_CONFIGURATION_ID = {"type": "string",
                     "description": "Matter configuration id (uuid4 hex)."}

MATTER_TOOLS: tuple[McpTool, ...] = (
    registry_tool(
        "warp_forge.matter.configurations.create",
        tool_name="create_matter_configuration", role=Role.DESIGNER,
        title="Create a matter configuration",
        description=("Create a matter configuration from trusted capabilities. "
                     "NOT AVAILABLE in this phase: the registry declares the "
                     "tool but no implementation is wired, so this call fails "
                     "loud and is audited.  Derive configurations with "
                     "warp_forge.matter.configurations.mutate instead."),
        arguments={"genome": {"type": "object",
                              "description": "Matter genome payload."}},
    ),
    registry_tool(
        "warp_forge.matter.configurations.mutate",
        tool_name="mutate_matter_configuration", role=Role.DESIGNER,
        title="Mutate a matter configuration",
        description=("Apply an allowlisted mutation operator to an allowlisted "
                     "parent configuration.  Both allowlists come from the "
                     "program's policy and fail closed; autonomy Level 1+ is "
                     "required."),
        arguments={
            "configuration_id": _CONFIGURATION_ID,
            "operator": {"type": "string",
                         "description": "Mutation operator name (must be allowlisted)."},
            "seed": {"type": "integer", "description": "Deterministic mutation seed."},
            "target": {"type": "string",
                       "description": "Component the operator targets, e.g. 'stack'."},
            "parameters": {"type": "object",
                           "description": "Operator parameters."},
            "reason": {"type": "string", "description": "Why this mutation."},
        },
        required=("configuration_id", "operator", "seed"),
        reservation=Reservation(
            argument="child_id", object_type="matter_configuration",
            result_key="configuration_id",
            loader=store.load_matter_configuration),
    ),
    registry_tool(
        "warp_forge.matter.configurations.simulate",
        tool_name="submit_matter_analysis", role=Role.DESIGNER,
        title="Run a matter analysis",
        description=("Submit a matter configuration through the real Warp Forge "
                     "solver funnel and bundle path.  Only allowlisted "
                     "configurations, or direct children of one, are accepted; "
                     "SAGE cannot bypass validation, gates, or confidence "
                     "ceilings."),
        arguments={
            "configuration_id": _CONFIGURATION_ID,
            "max_gate": {"type": "integer",
                         "description": "Highest solver-funnel gate to attempt."},
            "seed": {"type": "integer", "description": "Deterministic analysis seed."},
        },
        required=("configuration_id",),
        reservation=Reservation(
            argument="analysis_id", object_type="matter_analysis",
            result_key="analysis_id", loader=store.load_matter_analysis),
    ),
)

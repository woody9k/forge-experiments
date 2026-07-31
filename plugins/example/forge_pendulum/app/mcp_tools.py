"""The same reads over the MCP surface.

MCP tools bind SAGE tool *names*: the MCP adapter dispatches through
``sage_tools.call_tool``, so a tool exposed here inherits the identical
policy check, role scoping and audit row. There is no second path.

These were written against an imagined signature — ``registry_tool_name=``
and ``schema=`` instead of ``tool_name=`` and ``arguments=``/``required=`` —
and nothing caught it, because ``add_mcp_tools`` takes a *callable* that is
only resolved when something actually builds the MCP tool table. The plugin
registered fine, ``/api/v1/plugins`` counted the contribution, and the
platform's MCP server raised ``TypeError`` on startup for anyone who had this
plugin installed. Resolve your lazy contributions in a test.
"""

from __future__ import annotations

from apps.mcp._core import McpTool, registry_tool
from forge_sage import Role

PENDULUM_TOOLS: tuple[McpTool, ...] = (
    registry_tool(
        "pendulum.runs.list",
        tool_name="list_pendulum_runs", role=Role.ANALYST,
        title="List pendulum runs",
        description="List pendulum experiment runs, most recent first.",
        arguments={"limit": {"type": "integer", "minimum": 1, "maximum": 200,
                             "description": "How many runs to return."}},
    ),
    registry_tool(
        "pendulum.period.predict",
        tool_name="predict_pendulum_period", role=Role.PLANNER,
        title="Predict a small-angle period",
        description=("Closed-form small-angle period T = 2*pi*sqrt(L/g) for a "
                     "pendulum length. A prediction, not a measurement: the "
                     "approximation degrades above a few degrees."),
        arguments={"length_m": {"type": "number", "exclusiveMinimum": 0,
                                "description": "Pendulum length in metres."}},
        required=("length_m",),
    ),
)

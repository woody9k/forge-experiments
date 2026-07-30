"""The same reads over the MCP surface.

MCP tools bind SAGE tool *names*: the MCP adapter dispatches through
``sage_tools.call_tool``, so a tool exposed here inherits the identical
policy check, role scoping and audit row. There is no second path.
"""

from __future__ import annotations

from apps.mcp._core import McpTool, registry_tool
from forge_sage import Role


PENDULUM_TOOLS: tuple[McpTool, ...] = (
    registry_tool(
        name="pendulum.runs.list",
        registry_tool_name="list_pendulum_runs",
        role=Role.ANALYST,
        description="List pendulum experiment runs.",
        schema={"type": "object", "properties": {
            "limit": {"type": "integer", "minimum": 1, "maximum": 200}}},
    ),
    registry_tool(
        name="pendulum.period.predict",
        registry_tool_name="predict_pendulum_period",
        role=Role.PLANNER,
        description="Closed-form small-angle period for a pendulum length.",
        schema={"type": "object", "required": ["length_m"], "properties": {
            "length_m": {"type": "number", "exclusiveMinimum": 0}}},
    ),
)

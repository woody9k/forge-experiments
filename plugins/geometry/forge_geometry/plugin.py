"""Geometry plugin declaration (forge-experiments).

Registered with Forge through the ``forge.plugins`` entry point declared in
this repository's pyproject.  The manifest and register hook are unchanged
from the in-platform version — that was the point of Phase 2: the shape a
plugin registers with does not depend on which repository it lives in.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from forge_sdk import PluginManifest, SagePack, SimplePlugin


def _metric_catalogue() -> str:
    """The trusted metrics' names, hashes and *parameter names*, as markdown.

    The policy allowlist is a list of content hashes, which tells a model
    which metrics it may use and nothing about how to address them. A live
    run made the consequence concrete: given only hashes, the designer
    produced a correct three-arm velocity sweep on the right metric and
    invented the parameter names (`velocity_units_c`, `warp_width_s`,
    `bubble_radius_m`), so `validate_arm` rejected the plan before a human
    was asked to approve it. Nothing was wrong with the reasoning — the
    vocabulary was never supplied.

    Built at registration from the metric library rather than written into
    `pack.md`, because parameter names are data: a metric added to the plugin
    appears here without anyone remembering to update prose.
    """
    from forge_metrics import builtin_metrics, load_metric_file

    lines = ["", "## Trusted metric catalogue", "",
             "Address a metric by its exact `metric_hash`. Parameter names "
             "must match this table exactly — a name not listed here is "
             "rejected at design time, before approval.", ""]
    for name, path in sorted(builtin_metrics().items()):
        definition = load_metric_file(path).definition
        parameters = ", ".join(
            f"`{key}` (default {spec.default:g})"
            for key, spec in sorted(definition.parameters.items())) or "none"
        lines.append(f"- **{name}** — hash `{definition.hash}`; "
                     f"coordinates {', '.join(definition.coordinates)}; "
                     f"parameters: {parameters}")
    return "\n".join(lines) + "\n"


def _pack() -> SagePack:
    content = (resources.files("forge_geometry") / "sage" / "pack.md").read_text()
    return SagePack(name="geometry", version="2",
                    content=content + _metric_catalogue())


def _register(registry) -> None:
    from forge_geometry.app.api import router
    from forge_geometry.app.queue_tasks import TASK_TYPES
    from forge_geometry.app.sage_tools import TOOLS
    from forge_geometry.app.store import GeometryBase
    from forge_geometry.selftests import SUITES

    registry.add_api_router(router)
    for spec, handler in TOOLS:
        registry.add_sage_tool(spec, handler)
    for suite in SUITES:
        registry.add_selftest_suite(suite)
    for task_type in TASK_TYPES:
        registry.add_task_type(task_type)
    registry.add_persistence_metadata(GeometryBase.metadata)
    registry.add_sage_pack(_pack())

    # How this domain runs a comparative experiment inside the governed
    # research loop (platform backlog P-9).  Until this was registered,
    # `sage_protocol.resolve("geometry")` raised and a geometry research
    # program died at `design` — the domain with the physics in it was the
    # one SAGE could not investigate.
    from forge_geometry.app.protocol import PROTOCOL

    registry.add_experiment_protocol(PROTOCOL)

    def _mcp_tools():
        # Lazy: MCP tools bind SAGE tool names, which exist only after every
        # plugin has registered and the allowlist sync has run.
        from forge_geometry.app.mcp_tools import GEOMETRY_TOOLS

        return GEOMETRY_TOOLS

    registry.add_mcp_tools(_mcp_tools)
    registry.add_ui_module(
        Path(str(resources.files("forge_geometry") / "ui" / "geometry.js")), "geometry.js")


plugin = SimplePlugin(
    PluginManifest(
        id="geometry",
        display_name="Spacetime Geometry (Metric Forge)",
        version="0.4.0",
        description="Trusted metric library, symbolic tensor-pipeline "
                    "experiments, and energy-condition validation.",
        owner="woody9k/forge-experiments",
        compatible_forge=">=0.4,<0.5",
        capabilities=[{"name": "geometry", "version": 1}],
    ),
    register=_register,
)

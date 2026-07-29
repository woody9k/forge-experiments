"""Geometry plugin declaration (forge-experiments).

Registered with Forge through the ``forge.plugins`` entry point declared in
this repository's pyproject.  The manifest and register hook are unchanged
from the in-platform version — that was the point of Phase 2: the shape a
plugin registers with does not depend on which repository it lives in.
"""

from __future__ import annotations

from importlib import resources

from forge_sdk import PluginManifest, SagePack, SimplePlugin


def _pack() -> SagePack:
    content = (resources.files("forge_geometry") / "sage" / "pack.md").read_text()
    return SagePack(name="geometry", version="1", content=content)


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

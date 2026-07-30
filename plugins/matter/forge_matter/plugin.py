"""Matter plugin declaration (forge-experiments).

Registered through the ``forge.plugins`` entry point in this repository's
pyproject.  The 501 campaign gate is declared as a safety policy so the
deliberate limitation is visible in plugin metadata, not only in code.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from forge_sdk import PluginManifest, SagePack, SimplePlugin


def _pack() -> SagePack:
    content = (resources.files("forge_matter") / "sage" / "pack.md").read_text()
    return SagePack(name="matter", version="1", content=content)


def _register(registry) -> None:
    from forge_matter.app.api import router
    from forge_matter.app.sage_tools import TOOLS
    from forge_matter.app.store import MatterBase

    registry.add_api_router(router)
    for spec, handler in TOOLS:
        registry.add_sage_tool(spec, handler)
    registry.add_persistence_metadata(MatterBase.metadata)
    registry.add_sage_pack(_pack())

    # How this domain runs a comparative experiment inside the governed
    # research loop (platform backlog P-4).  The loop drives it; the
    # platform keeps the state machine, gates, idempotency and audit.
    from forge_matter.app.protocol import PROTOCOL

    registry.add_experiment_protocol(PROTOCOL)

    def _mcp_tools():
        # Lazy: MCP tools bind SAGE tool names, which exist only after every
        # plugin has registered and the allowlist sync has run.
        from forge_matter.app.mcp_tools import MATTER_TOOLS

        return MATTER_TOOLS

    registry.add_mcp_tools(_mcp_tools)
    registry.add_ui_module(
        Path(str(resources.files("forge_matter") / "ui" / "matter.js")), "matter.js")


plugin = SimplePlugin(
    PluginManifest(
        id="matter",
        display_name="Matter Forge",
        version="0.4.0",
        description="Physically parameterized matter configurations: "
                    "genome→phenotype compilation, Casimir and classical "
                    "models, mutation and lineage.",
        owner="woody9k/forge-experiments",
        compatible_forge=">=0.4,<0.5",
        safety_policies=[
            "Campaign execution (POST /api/v1/matter/campaigns) returns 501 "
            "until gates B-2, B-5, B-7, B-13, B-18 close "
            "(docs/matter-forge-design.md §9).",
        ],
    ),
    register=_register,
)

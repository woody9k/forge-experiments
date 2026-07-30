"""The plugin declaration — the whole contract in one file.

Read this next to the manifest fields in `forge_sdk.manifest` and the
contribution points in `forge_sdk.registry`; between them they are the entire
surface a plugin has to satisfy.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from forge_sdk import PluginManifest, SagePack, SimplePlugin


def _pack() -> SagePack:
    content = (resources.files("forge_pendulum") / "sage" / "pack.md").read_text()
    return SagePack(name="pendulum", version="1", content=content)


def _register(registry) -> None:
    """Everything this plugin adds to the platform.

    Imports are inside the hook so a platform that never activates this
    plugin never pays for them — and so a broken import disables *this*
    plugin rather than breaking startup.
    """
    from forge_pendulum.app.api import router
    from forge_pendulum.app.sage_tools import TOOLS
    from forge_pendulum.app.store import PendulumBase
    from forge_pendulum.app.tasks import TASK_TYPES
    from forge_pendulum.selftests import SUITES

    registry.add_api_router(router)
    for spec, handler in TOOLS:
        registry.add_sage_tool(spec, handler)
    for suite in SUITES:
        registry.add_selftest_suite(suite)
    for task_type in TASK_TYPES:
        registry.add_task_type(task_type)
    registry.add_persistence_metadata(PendulumBase.metadata)
    registry.add_sage_pack(_pack())

    # How this domain runs a comparative experiment inside the governed
    # research loop (platform backlog P-4).  The loop drives it; the
    # platform keeps the state machine, gates, idempotency and audit.
    from forge_pendulum.app.protocol import PROTOCOL

    registry.add_experiment_protocol(PROTOCOL)

    def _mcp_tools():
        # Lazy: MCP tools bind SAGE tool names, which exist only after every
        # plugin has registered and the allowlist sync has run.
        from forge_pendulum.app.mcp_tools import PENDULUM_TOOLS

        return PENDULUM_TOOLS

    registry.add_mcp_tools(_mcp_tools)
    registry.add_ui_module(
        Path(str(resources.files("forge_pendulum") / "ui" / "pendulum.js")),
        "pendulum.js")


plugin = SimplePlugin(
    PluginManifest(
        id="pendulum",
        display_name="Pendulum Lab (example plugin)",
        version="1.0.0",
        description="Reference plugin: a damped pendulum whose period is "
                    "measured and checked against the small-angle closed form.",
        owner="woody9k/forge-experiments",
        compatible_forge=">=0.4,<0.5",
        capabilities=[{"name": "pendulum-lab", "version": 1}],
        safety_policies=[
            "Runs are bounded: the integrator rejects timesteps above 0.05 s "
            "and amplitudes beyond ±170°, so a run cannot be made unbounded "
            "or unstable through tool arguments.",
        ],
    ),
    register=_register,
)

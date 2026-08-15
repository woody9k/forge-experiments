from importlib import resources
from pathlib import Path

from forge_sdk import PluginManifest, SimplePlugin


def _register(registry) -> None:
    from forge_lattice.app.api import router
    from forge_lattice.app.sage_tools import TOOLS

    registry.add_api_router(router)
    for spec, handler in TOOLS:
        registry.add_sage_tool(spec, handler)
    registry.add_ui_module(
        Path(str(resources.files("forge_lattice") / "ui" / "lattice.js")),
        "lattice.js")


plugin = SimplePlugin(PluginManifest(
    id="lattice", display_name="Forge Lattice", version="0.1.0",
    description="Conservative electromagnetic estimates for engineered layered material stacks, beginning with Mg-Zn/Bi under DC and RF excitation.",
    owner="woody9k/forge-experiments", compatible_forge=">=0.4,<0.5",
    capabilities=[{"name": "layered-field-response", "version": 1}],
    safety_policies=[
        "Inputs are finite and bounded; the model executes no arbitrary code.",
        "Conventional EM estimates are labeled separately from weak-field gravity scales.",
        "Weak-field outputs may not be represented as anomalous gravity, propulsion, or metric-engineering evidence.",
    ]), register=_register)

"""Matter-domain SAGE tools (platform-split Phase 2).

Implementations moved verbatim from ``apps/coordinator/sage_tools.py``; the
tool specs moved from the static registry in ``forge_sage.tools``.  Both are
contributed through the matter plugin declaration (``apps/api/matter.py``)
and synced by ``apps/plugins/registry.py``.

``create_matter_configuration`` is declared with no handler — the tool is
authorized like any other but execution reports it unavailable (backlog
S-3/S-4), exactly as the static registry did.
"""

from __future__ import annotations

from apps.coordinator import store
import forge_matter.app.store as mstore
from apps.coordinator.sage_tools import ToolExecutionError, _safe_id
from forge_matter import materials as matter_materials
from forge_matter.mutations import OPERATORS as MUTATION_OPERATORS
from forge_sage import Role
from forge_sage.policies import RiskClass
from forge_sage.tools import read_tool, write_tool

_ALL = set(Role)


# ------------------------------------------------------------------ read impls

def _list_matter_models(program, args):
    """The predicted-effect model families actually implemented in v0.2."""
    return {"models": [
        {"id": "casimir_parallel_plate", "kind": "predicted_effect_model",
         "confidence_ceiling": "C3"},
        {"id": "classical_gravity", "kind": "predicted_effect_model",
         "confidence_ceiling": "C3"},
    ], "materials_db_version": matter_materials.database_version(),
       "mutation_operators": sorted(MUTATION_OPERATORS)}


def _get_matter_configuration(program, args):
    cfg = mstore.load_matter_configuration(args["configuration_id"])
    if cfg is None:
        raise ToolExecutionError(
            f"unknown matter configuration {args['configuration_id']!r}")
    return cfg


def _get_material(program, args):
    mid = args["material_id"]
    db = matter_materials.list_materials()
    if mid not in db:
        raise ToolExecutionError(f"unknown material {mid!r}")
    return {"id": mid, "properties": db[mid],
            "database_version": matter_materials.database_version()}


def _list_instruments(program, args):
    """v0.2 has predicted-effect models, not dedicated instrument models."""
    return {"instruments": [], "note": (
        "dedicated instrument-response models are backlog B-19; use "
        "list_matter_models for the implemented predicted-effect models")}


# ----------------------------------------------------------------- write impls

def _mutate_matter_configuration(program, args):
    """Apply an allowlisted mutation operator to an allowlisted configuration.

    Both allowlists fail closed: an operator or parent configuration not
    explicitly granted by the program's policy is refused regardless of what
    the model asked for.
    """
    from forge_matter import MatterConfiguration
    from forge_matter.mutations import MutationError, mutate

    parent_id = _safe_id(args["configuration_id"])
    operator = str(args["operator"])
    if parent_id not in program.policy.allowed_matter_versions:
        raise ToolExecutionError(
            f"configuration {parent_id!r} is not allowlisted for this program")
    if operator not in program.policy.allowed_mutation_operators:
        raise ToolExecutionError(
            f"mutation operator {operator!r} is not allowlisted for this program")
    parent_payload = mstore.load_matter_configuration(parent_id)
    if parent_payload is None:
        raise ToolExecutionError(f"unknown configuration {parent_id!r}")
    parent = MatterConfiguration.model_validate(parent_payload)
    params = {"target": args.get("target"), **args.get("parameters", {})}
    try:
        child = mutate(parent, operator, params, seed=int(args["seed"]),
                       reason=str(args.get("reason", "sage plan mutation")))
    except MutationError as exc:
        raise ToolExecutionError(str(exc)) from exc
    if args.get("child_id"):
        child.id = _safe_id(args["child_id"])  # caller-reserved (ledger-first)
    mstore.save_matter_configuration(child)
    return {"configuration_id": child.id, "genome_hash": child.genome_hash,
            "generation": child.generation}


def _submit_matter_analysis(program, args):
    """Run one matter analysis through the existing funnel + bundle path.

    Only allowlisted configurations — or direct children created by this
    program's own allowlisted mutations — may be analyzed.  The analysis goes
    through the exact same ``analyze_and_bundle`` path the human-facing flow
    uses: SAGE cannot bypass Warp Forge validation.
    """
    from forge_matter.app.runner import analyze_and_bundle
    from forge_matter import MatterConfiguration

    config_id = _safe_id(args["configuration_id"])
    payload = mstore.load_matter_configuration(config_id)
    if payload is None:
        raise ToolExecutionError(f"unknown configuration {config_id!r}")
    config = MatterConfiguration.model_validate(payload)
    allowed = program.policy.allowed_matter_versions
    if config_id not in allowed and not (set(config.parent_ids) & set(allowed)):
        raise ToolExecutionError(
            f"configuration {config_id!r} is neither allowlisted nor a direct "
            f"child of an allowlisted configuration")
    reserved = _safe_id(args["analysis_id"]) if args.get("analysis_id") else None
    analysis, bundle = analyze_and_bundle(
        config, max_gate=int(args.get("max_gate", 2)),
        seed=int(args.get("seed", 0)), analysis_id=reserved)
    mstore.save_matter_analysis(analysis)
    return {"analysis_id": analysis.id, "status": analysis.status,
            "highest_gate_completed": analysis.highest_gate_completed,
            "bundle": bundle.name}


#: (spec, handler) contributions the matter plugin registers.
#: ``create_matter_configuration`` deliberately has no handler yet.
TOOLS = [
    (read_tool("list_matter_models", _ALL, "List available matter models."),
     _list_matter_models),
    (read_tool("get_matter_configuration", _ALL,
               "Fetch a matter configuration."),
     _get_matter_configuration),
    (read_tool("get_material", _ALL, "Fetch a material from the materials DB."),
     _get_material),
    (read_tool("list_instruments", _ALL, "List predicted-effect instruments."),
     _list_instruments),
    (write_tool("create_matter_configuration", RiskClass.R2_BOUNDED_EXPERIMENT,
                {Role.DESIGNER},
                "Create a matter configuration from trusted capabilities."),
     None),
    (write_tool("mutate_matter_configuration", RiskClass.R2_BOUNDED_EXPERIMENT,
                {Role.DESIGNER},
                "Apply an allowlisted mutation operator to a configuration."),
     _mutate_matter_configuration),
    (write_tool("submit_matter_analysis", RiskClass.R2_BOUNDED_EXPERIMENT,
                {Role.DESIGNER},
                "Submit an approved matter analysis to Warp Forge."),
     _submit_matter_analysis),
]

"""Matter Forge API (v1).

Gates 0–2 are sub-second analytic evaluations and run inline; Gate 3+ will
route through the worker queue when implemented. Campaign *execution* is
explicitly unavailable pending the gating items in
docs/matter-forge-design.md §9 — the endpoint says so rather than
pretending.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
from fastapi import APIRouter, HTTPException

from apps.coordinator import store
from apps.coordinator.matter_runner import analyze_and_bundle, compare_with_parent
from forge_matter import casimir, materials
from forge_matter.compiler import CompileError, compile_configuration, load_configuration
from forge_matter.entities import MatterAnalysis, MatterConfiguration, ValidationState
from forge_matter.mutations import OPERATORS, MutationError, mutate

router = APIRouter(prefix="/api/v1/matter", tags=["matter"])

_CAMPAIGN_SCHEMA = Path(__file__).resolve().parents[2] / "schemas" / "matter-campaign.schema.json"

SEARCH_GATING = [
    "B-2 independent solver verification",
    "B-5 geodesic and tidal diagnostics",
    "B-7 quarantine/promotion workflow",
    "B-13 worker capability enforcement",
    "B-18 proper-volume energy accounting",
]


# ------------------------------------------------------------------ library

@router.get("/materials")
def get_materials() -> dict:
    return {"version": materials.database_version(),
            "materials": materials.list_materials()}


@router.get("/instruments")
def get_instruments() -> dict:
    return {
        "implemented": [],
        "scheduled": ["optical_interferometer", "microwave_cavity",
                      "atomic_interferometer", "atomic_clock_pair",
                      "torsion_balance", "gravimeter", "gyroscope",
                      "accelerometer", "test_particle_trajectory",
                      "photon_time_of_flight"],
        "note": "instrument models arrive with Gate 3 (docs/backlog.md); "
                "Gate 2 reports raw effect proxies with confidence labels",
    }


@router.get("/casimir/models")
def get_casimir_models() -> dict:
    return {"module_version": casimir.MODULE_VERSION, "models": casimir.MODELS}


@router.post("/casimir/analyze")
def casimir_analyze(body: dict) -> dict:
    try:
        result = casimir.ideal_parallel_plates(
            separation_m=float(body["separation_m"]),
            plate_area_m2=float(body["plate_area_m2"]),
            plate_count=int(body.get("plate_count", 2)),
            temperature_k=float(body.get("temperature_k", 0.0)),
            apparatus_rest_energy_j=float(body.get("apparatus_rest_energy_j", 0.0)),
        )
    except (KeyError, ValueError, casimir.CasimirModelError) as exc:
        raise HTTPException(422, str(exc)) from exc
    out = result.__dict__.copy()
    out["energy_account"] = result.energy_account.model_dump()
    out["confidence"] = f"C{int(result.confidence)}"
    return out


# ------------------------------------------------------------ configurations

def _load_config(config_id: str) -> MatterConfiguration:
    payload = store.load_matter_configuration(config_id)
    if payload is None:
        raise HTTPException(404, "configuration not found")
    return MatterConfiguration.model_validate(payload)


@router.post("/configurations", status_code=201)
def create_configuration(genome: dict) -> dict:
    try:
        config = load_configuration(genome)
    except CompileError as exc:
        raise HTTPException(422, str(exc)) from exc
    store.save_matter_configuration(config)
    return {"id": config.id, "genome_hash": config.genome_hash,
            "validation_state": config.validation_state.value}


@router.get("/configurations")
def list_configurations(limit: int = 100) -> list[dict]:
    return store.list_matter_configurations(limit=min(limit, 500))


@router.get("/configurations/{config_id}")
def get_configuration(config_id: str) -> dict:
    return _load_config(config_id).model_dump(mode="json")


@router.post("/configurations/{config_id}/validate")
def validate_configuration(config_id: str) -> dict:
    config = _load_config(config_id)
    try:
        phenotype = compile_configuration(config)
    except CompileError as exc:
        return {"valid": False, "error": str(exc)}
    config.validation_state = ValidationState.VALIDATED
    store.save_matter_configuration(config)
    return {"valid": True, "phenotype_hash": phenotype["phenotype_hash"],
            "warnings": phenotype["warnings"]}


@router.post("/configurations/{config_id}/compile")
def compile_endpoint(config_id: str) -> dict:
    config = _load_config(config_id)
    try:
        return compile_configuration(config)
    except CompileError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/configurations/{config_id}/simulate", status_code=202)
def simulate_configuration(config_id: str, max_gate: int = 2, seed: int = 0) -> dict:
    config = _load_config(config_id)
    if max_gate > 2:
        raise HTTPException(
            422, "gates 3–5 are not implemented; requested gates will be "
                 "reported as not_implemented — call with max_gate<=2, or see "
                 "docs/matter-forge-design.md §6")
    analysis, bundle = analyze_and_bundle(config, max_gate=max_gate, seed=seed)
    store.save_matter_configuration(config)  # phenotype hash now filled
    store.save_matter_analysis(analysis)
    return {"analysis_id": analysis.id, "status": analysis.status,
            "highest_gate_completed": analysis.highest_gate_completed,
            "bundle": bundle.name}


@router.get("/configurations/{config_id}/stress-energy")
def stress_energy(config_id: str) -> dict:
    analyses = store.matter_analyses_for(config_id)
    if not analyses:
        raise HTTPException(404, "no analyses for this configuration; simulate first")
    latest = analyses[0]
    return {"analysis_id": latest["id"],
            "contributions": latest["contributions"],
            "energy_account": latest["energy_account"]}


@router.post("/configurations/{config_id}/mutate", status_code=201)
def mutate_configuration(config_id: str, body: dict) -> dict:
    parent = _load_config(config_id)
    try:
        child = mutate(parent, body["operator"], body.get("params", {}),
                       seed=int(body.get("seed", 0)),
                       reason=body.get("reason", ""))
    except (KeyError, MutationError) as exc:
        raise HTTPException(422, str(exc)) from exc
    store.save_matter_configuration(child)
    return {"id": child.id, "parent_id": parent.id,
            "generation": child.generation,
            "mutation": child.mutation_history[-1].model_dump(mode="json"),
            "operators_available": sorted(OPERATORS)}


@router.post("/configurations/{config_id}/branch", status_code=201)
def branch_configuration(config_id: str, body: dict | None = None) -> dict:
    parent = _load_config(config_id)
    child = MatterConfiguration(
        name=parent.name, version=parent.version,
        description=(body or {}).get("note", f"branch of {parent.id[:12]}"),
        genome=parent.genome, parent_ids=[parent.id],
        generation=parent.generation + 1,
        mutation_history=parent.mutation_history,
    )
    store.save_matter_configuration(child)
    return {"id": child.id, "parent_id": parent.id}


@router.get("/configurations/{config_id}/lineage")
def lineage(config_id: str) -> dict:
    config = _load_config(config_id)
    ancestors = []
    cursor = config
    while cursor.parent_ids:
        payload = store.load_matter_configuration(cursor.parent_ids[0])
        if payload is None:
            break
        cursor = MatterConfiguration.model_validate(payload)
        ancestors.append({"id": cursor.id, "generation": cursor.generation,
                          "genome_hash": cursor.genome_hash})
    return {
        "id": config.id, "generation": config.generation,
        "mutation_history": [m.model_dump(mode="json") for m in config.mutation_history],
        "ancestors": ancestors,
        "children": store.matter_children(config.id),
    }


@router.get("/configurations/{config_id}/compare-parent")
def compare_parent(config_id: str) -> dict:
    config = _load_config(config_id)
    if not config.parent_ids:
        raise HTTPException(422, "configuration has no parent")
    child_analyses = store.matter_analyses_for(config_id)
    parent_analyses = store.matter_analyses_for(config.parent_ids[0])
    if not child_analyses or not parent_analyses:
        raise HTTPException(404, "both configurations must be simulated first")
    return compare_with_parent(
        MatterAnalysis.model_validate(parent_analyses[0]),
        MatterAnalysis.model_validate(child_analyses[0]))


# ---------------------------------------------------------------- campaigns

@router.post("/campaigns")
def create_campaign(spec: dict) -> dict:
    try:
        jsonschema.validate(spec, json.loads(_CAMPAIGN_SCHEMA.read_text()))
    except jsonschema.ValidationError as exc:
        raise HTTPException(422, f"campaign spec invalid: {exc.message}") from exc
    raise HTTPException(
        501,
        detail={
            "message": "campaign spec is schema-valid, but campaign execution "
                       "is not available in v0.2.0",
            "gated_on": SEARCH_GATING,
            "reference": "docs/matter-forge-design.md §9",
        })


@router.get("/campaigns")
def list_campaigns() -> dict:
    return {"campaigns": [], "execution_available": False,
            "gated_on": SEARCH_GATING}


# --------------------------------------------------------------- plugin decl
# In-repo plugin registration (platform-split Phase 2).  Destined to become a
# forge.plugins entry point in the forge-experiments repo.

from forge_sdk import PluginManifest, SimplePlugin  # noqa: E402



def _load_pack(name):
    from pathlib import Path
    from forge_sdk import SagePack

    path = Path(__file__).resolve().parents[2] / "prompts" / "sage" / "packs" / f"{name}.md"
    return SagePack(name=name, version="1", content=path.read_text())

def _register(registry):
    from apps.coordinator.sage_tools_matter import TOOLS as _SAGE_TOOLS
    from apps.coordinator.store_matter import MatterBase

    registry.add_api_router(router)
    for spec, handler in _SAGE_TOOLS:
        registry.add_sage_tool(spec, handler)
    registry.add_persistence_metadata(MatterBase.metadata)
    registry.add_sage_pack(_load_pack("matter"))


plugin = SimplePlugin(
    PluginManifest(
        id="matter",
        display_name="Matter Forge",
        version="0.4.0",
        description="Physically parameterized matter configurations: "
                    "genome→phenotype compilation, Casimir and classical "
                    "models, mutation and lineage.",
        compatible_forge=">=0.4,<0.5",
        safety_policies=[
            "Campaign execution (POST /api/v1/matter/campaigns) returns 501 "
            "until gates B-2, B-5, B-7, B-13, B-18 close "
            "(docs/matter-forge-design.md §9).",
        ],
    ),
    register=_register,
)

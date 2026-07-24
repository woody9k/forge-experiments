"""Matter analysis runner: funnel execution + reproducible bundles.

Application-layer glue (packages stay pure): runs the forge_matter funnel,
then writes the same style of self-contained, checksummed bundle the metric
experiments use. Bundles live beside them under EXPERIMENTS_DIR with the
`matter-` prefix.
"""

from __future__ import annotations

import json
from pathlib import Path

from apps.coordinator.provenance import (
    container_image_digest, dependency_versions, file_checksum, source_commit,
)
from apps.coordinator.runner import experiments_dir
from forge_matter.compiler import compile_configuration
from forge_matter.entities import MatterAnalysis, MatterConfiguration
from forge_matter.funnel import FUNNEL_VERSION, run_funnel


def _dump(path: Path, obj) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str))
    return file_checksum(path)


def analyze_and_bundle(config: MatterConfiguration, max_gate: int = 2,
                       seed: int = 0,
                       analysis_id: str | None = None) -> tuple[MatterAnalysis, Path]:
    """Run the funnel and write the checksummed bundle.

    ``analysis_id``, when given, is a caller-reserved id (e.g. from SAGE's
    idempotency ledger) assigned to the analysis before bundling, so a crashed
    submission can be completed under the same id instead of duplicating.
    """
    analysis = run_funnel(config, max_gate=max_gate, seed=seed)
    if analysis_id is not None:
        analysis.id = analysis_id
    bundle = experiments_dir() / f"matter-{analysis.id}"
    bundle.mkdir(parents=True, exist_ok=True)

    checksums = {}
    checksums["configuration.json"] = _dump(
        bundle / "configuration.json", config.model_dump(mode="json"))
    if analysis.highest_gate_completed >= 0:
        phenotype = compile_configuration(config)
        checksums["phenotype.json"] = _dump(bundle / "phenotype.json", phenotype)
    checksums["analysis.json"] = _dump(
        bundle / "analysis.json", analysis.model_dump(mode="json"))

    manifest = {
        "kind": "matter_analysis",
        "analysis_id": analysis.id,
        "configuration_id": config.id,
        "genome_hash": config.genome_hash,
        "phenotype_hash": analysis.phenotype_hash,
        "compiler_version": analysis.compiler_version,
        "material_db_version": analysis.material_db_version,
        "funnel_version": FUNNEL_VERSION,
        "highest_gate_completed": analysis.highest_gate_completed,
        "status": analysis.status,
        "random_seed": seed,
        "source_commit": source_commit(),
        "container_image_digest": container_image_digest(),
        "dependency_versions": dependency_versions(),
        "warnings": analysis.warnings,
        "artifact_checksums": checksums,
    }
    _dump(bundle / "manifest.json", manifest)
    (bundle / "summary.md").write_text(_summary_md(config, analysis))
    return analysis, bundle


def _summary_md(config: MatterConfiguration, analysis: MatterAnalysis) -> str:
    lines = [
        f"# Matter analysis {analysis.id}",
        "",
        f"* Configuration: **{config.name}** v{config.version} "
        f"(genome `{config.genome_hash[:12]}`, phenotype `{analysis.phenotype_hash[:12]}`)",
        f"* Generation {config.generation}"
        + (f", parents: {', '.join(p[:12] for p in config.parent_ids)}"
           if config.parent_ids else " (root)"),
        f"* Status: **{analysis.status}**, highest gate completed: "
        f"{analysis.highest_gate_completed}",
        "",
        "## Gates", "",
        "| gate | name | status | checks passed |",
        "|---|---|---|---|",
    ]
    for g in analysis.gates:
        ok = sum(1 for c in g.checks if c["passed"])
        lines.append(f"| {g.gate} | {g.name} | {g.status.value} | {ok}/{len(g.checks)} |")
    if analysis.effects:
        lines += ["", "## Predicted effects", "",
                  "| region | effect | value | units | confidence | model |",
                  "|---|---|---|---|---|---|"]
        for e in analysis.effects:
            val = f"{e.value:.6e}" if e.value is not None else "not computable"
            lines.append(f"| {e.observation_region_id} | {e.effect} | "
                         f"{val} | {e.units} | C{int(e.confidence)} | {e.model} |")
    if analysis.energy_account:
        a = analysis.energy_account
        lines += ["", "## Energy account", "",
                  f"* local min energy density: {a.local_min_energy_density_j_m3} J/m³",
                  f"* integrated vacuum energy: {a.integrated_vacuum_energy_j:.6e} J",
                  f"* apparatus rest energy: {a.apparatus_rest_energy_j:.6e} J",
                  f"* support energy: {a.support_energy_j:.6e} J",
                  f"* **total system energy: {a.total_system_energy_j:.6e} J**",
                  "", f"> {a.warning}"]
    if config.mutation_history:
        lines += ["", "## Mutation history", ""]
        for m in config.mutation_history:
            lines.append(f"* `{m.operator}@{m.operator_version}` seed {m.seed}: "
                         f"{m.parameters_before} → {m.parameters_after}")
    if analysis.warnings:
        lines += ["", "## Warnings", ""] + [f"* {w}" for w in analysis.warnings]
    return "\n".join(lines) + "\n"


def compare_with_parent(parent: MatterAnalysis, child: MatterAnalysis) -> dict:
    """Effect-by-effect and account-level deltas between two analyses."""
    def effect_map(a: MatterAnalysis) -> dict:
        return {(e.observation_region_id, e.effect): e.value for e in a.effects}

    pm, cm = effect_map(parent), effect_map(child)
    deltas = {}
    for key in sorted(set(pm) | set(cm)):
        p, c = pm.get(key), cm.get(key)
        deltas["/".join(key)] = {
            "parent": p, "child": c,
            "ratio": (c / p) if (p not in (None, 0.0) and c is not None
                                 and p == p and c == c) else None,
        }
    out = {"effects": deltas}
    if parent.energy_account and child.energy_account:
        out["vacuum_energy_j"] = {
            "parent": parent.energy_account.integrated_vacuum_energy_j,
            "child": child.energy_account.integrated_vacuum_energy_j,
        }
        out["local_min_energy_density_j_m3"] = {
            "parent": parent.energy_account.local_min_energy_density_j_m3,
            "child": child.energy_account.local_min_energy_density_j_m3,
        }
    return out

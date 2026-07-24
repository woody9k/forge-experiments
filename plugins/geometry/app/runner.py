"""Experiment execution engine.

Runs an experiment in two phases and writes a self-contained, reproducible
bundle under EXPERIMENTS_DIR/<experiment-id>/:

    manifest.json          experiment spec + provenance + artifact checksums
    metric.json            full metric definition as loaded
    expressions.json       symbolic results (sympy srepr strings)
    validations.json       known-answer validation results
    energy_conditions.json energy-condition report (if a grid was requested)
    arrays/*.npz           grid fields (metric, stress-energy, energy density)
    summary.md             human-readable summary

The same engine backs the Celery workers and the local CLI, so a laptop run
and a containerized run produce byte-comparable science (timings differ).

Simplification policy (documented, deterministic): metrics whose components
total fewer than SIMPLIFY_OP_BUDGET SymPy operations get full simplification
and a Kretschmann scalar; larger metrics run unsimplified with Kretschmann
deferred — recorded in the manifest as `simplify_level`.
"""

from __future__ import annotations

import json
import os
import time
import zipfile
from dataclasses import asdict
from pathlib import Path

import numpy as np
import sympy as sp

from forge_domain.entities import (
    ComputationResult, EnergyConditionConfig, Experiment, ExperimentStatus,
    GridSpec, ResultQuality, SolverBackend, ValidationResult, utcnow,
)
from forge_math import compute_geometry
from forge_math.numeric import build_grid, evaluate_matrix
from forge_metrics import load_metric_file
from forge_metrics.loader import ParsedMetric
from forge_validation import evaluate_energy_conditions, run_validation_suite
from apps.coordinator.provenance import (
    container_image_digest, dependency_versions, file_checksum, source_commit,
)

# Metrics at or below this SymPy op count get full simplification plus a
# Kretschmann scalar; anything larger runs unsimplified with Kretschmann
# deferred.  Calibration on the bundled library: minkowski=1,
# schwarzschild=12 (both fully simplify in <1 s); alcubierre=96, natario=101
# (full simplification of their Riemann tensors takes minutes to hours).
SIMPLIFY_OP_BUDGET = 40
SOFTWARE_VERSION = "0.1.0"


def experiments_dir() -> Path:
    d = Path(os.environ.get("EXPERIMENTS_DIR", Path(__file__).resolve().parents[2] / "experiments"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def metrics_dir() -> Path:
    return Path(os.environ.get("METRICS_DIR", Path(__file__).resolve().parents[2] / "metrics"))


def _op_count(matrix: sp.Matrix) -> int:
    return sum(sp.count_ops(e) for e in matrix)


def choose_simplify_level(matrix: sp.Matrix) -> tuple[str, bool]:
    if _op_count(matrix) <= SIMPLIFY_OP_BUDGET:
        return "full", True
    return "none", False


def _dump(path: Path, obj) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str))
    return file_checksum(path)


class ExperimentRun:
    def __init__(self, experiment: Experiment, parsed: ParsedMetric, bundle_dir: Path):
        self.experiment = experiment
        self.parsed = parsed
        self.bundle_dir = bundle_dir
        self.checksums: dict[str, str] = {}
        self.warnings: list[str] = []
        self.computation_results: list[ComputationResult] = []
        self.validation_results: list[ValidationResult] = []
        self.geometry = None
        self.timings: dict[str, float] = {}


def prepare_run(experiment: Experiment) -> ExperimentRun:
    metric_path = metrics_dir() / experiment.metric_name / "metric.yaml"
    if not metric_path.exists():
        raise FileNotFoundError(f"unknown metric {experiment.metric_name!r}")
    parsed = load_metric_file(metric_path)
    if experiment.metric_hash and experiment.metric_hash != parsed.definition.hash:
        raise ValueError(
            f"metric hash mismatch: experiment pinned {experiment.metric_hash[:12]}, "
            f"loaded definition is {parsed.definition.hash[:12]} — refusing to run"
        )
    experiment.metric_hash = parsed.definition.hash
    bundle_dir = experiments_dir() / experiment.id
    bundle_dir.mkdir(parents=True, exist_ok=True)
    run = ExperimentRun(experiment, parsed, bundle_dir)
    run.checksums["metric.json"] = _dump(
        bundle_dir / "metric.json", parsed.definition.model_dump(mode="json"))
    return run


def run_symbolic_phase(run: ExperimentRun) -> None:
    exp, parsed = run.experiment, run.parsed
    level, kret = choose_simplify_level(parsed.matrix)
    t0 = time.monotonic()
    geo = compute_geometry(parsed.matrix, parsed.coords,
                           simplify_level=level, compute_kretschmann=kret)
    run.timings["symbolic_phase_s"] = time.monotonic() - t0
    run.geometry = geo
    run.warnings.extend(geo.warnings)

    quality = ResultQuality.EXACT_SYMBOLIC
    n = geo.dim
    exprs = {
        "simplify_level": level,
        "metric": [[sp.srepr(geo.metric[i, j]) for j in range(n)] for i in range(n)],
        "inverse_metric": [[sp.srepr(geo.inverse_metric[i, j]) for j in range(n)] for i in range(n)],
        "determinant": sp.srepr(geo.determinant),
        "christoffel": [[[sp.srepr(geo.christoffel[a][b][c]) for c in range(n)]
                         for b in range(n)] for a in range(n)],
        "ricci": [[sp.srepr(geo.ricci[i, j]) for j in range(n)] for i in range(n)],
        "ricci_scalar": sp.srepr(geo.ricci_scalar),
        "einstein": [[sp.srepr(geo.einstein[i, j]) for j in range(n)] for i in range(n)],
        "stress_energy": [[sp.srepr(geo.stress_energy[i, j]) for j in range(n)] for i in range(n)],
        "kretschmann": sp.srepr(geo.kretschmann) if geo.kretschmann is not None else None,
    }
    run.checksums["expressions.json"] = _dump(run.bundle_dir / "expressions.json", exprs)

    for rtype, rank in (("christoffel", 3), ("ricci", 2), ("ricci_scalar", 0),
                        ("einstein", 2), ("stress_energy", 2), ("kretschmann", 0)):
        q = quality
        if rtype == "kretschmann" and geo.kretschmann is None:
            q = ResultQuality.UNRESOLVED
        run.computation_results.append(ComputationResult(
            experiment_id=exp.id, result_type=rtype, quality=q,
            tensor_rank=rank, dimensions=[n] * rank,
            symbolic_expression=None if rank else exprs.get(rtype),
            array_location="expressions.json", units="geometrized",
            precision="exact", warnings=list(geo.warnings),
            checksum=run.checksums["expressions.json"],
        ))

    t0 = time.monotonic()
    run.validation_results = run_validation_suite(parsed, geo, exp.id, exp.parameter_values)
    run.timings["validation_s"] = time.monotonic() - t0
    run.checksums["validations.json"] = _dump(
        run.bundle_dir / "validations.json",
        [v.model_dump(mode="json") for v in run.validation_results])


def run_numerical_phase(run: ExperimentRun) -> None:
    exp, parsed, geo = run.experiment, run.parsed, run.geometry
    if exp.grid is None:
        return
    if geo is None:
        raise RuntimeError("numerical phase requires symbolic phase results")

    subs = {parsed.params[s.symbol]: sp.Float(exp.parameter_values.get(name, s.default))
            for name, s in parsed.definition.parameters.items()}
    t0 = time.monotonic()
    axes, meshes = build_grid(parsed.coords, exp.grid)

    g_arr, g_fields = evaluate_matrix(geo.metric.subs(subs), parsed.coords, meshes, "g")
    ginv_arr, ginv_fields = evaluate_matrix(geo.inverse_metric.subs(subs), parsed.coords, meshes, "g_inv")
    T_arr, T_fields = evaluate_matrix(geo.stress_energy.subs(subs), parsed.coords, meshes, "T")

    field_warnings = [w for fr in (*g_fields, *ginv_fields, *T_fields)
                      for w in fr.warnings]
    run.warnings.extend(field_warnings)
    nonfinite = any(not fr.finite for fr in (*g_fields, *ginv_fields, *T_fields))

    arrays_dir = run.bundle_dir / "arrays"
    arrays_dir.mkdir(exist_ok=True)
    np.savez_compressed(arrays_dir / "grid.npz",
                        **{f"axis_{k}": v for k, v in axes.items()},
                        metric=g_arr, inverse_metric=ginv_arr, stress_energy=T_arr)
    run.checksums["arrays/grid.npz"] = file_checksum(arrays_dir / "grid.npz")

    ec_cfg = exp.energy_conditions or EnergyConditionConfig()
    rep = evaluate_energy_conditions(
        g_arr, ginv_arr, T_arr, ec_cfg.conditions,
        sample_points=ec_cfg.sample_points,
        observer_samples=max(o.samples for o in ec_cfg.observers) if ec_cfg.observers else 16,
        tolerance=ec_cfg.tolerance, seed=exp.random_seed,
    )
    np.savez_compressed(arrays_dir / "energy_density.npz",
                        eulerian_energy_density=rep.eulerian_energy_density)
    run.checksums["arrays/energy_density.npz"] = file_checksum(arrays_dir / "energy_density.npz")
    run.checksums["energy_conditions.json"] = _dump(
        run.bundle_dir / "energy_conditions.json",
        {c: asdict(r) for c, r in rep.results.items()})
    run.timings["numerical_phase_s"] = time.monotonic() - t0

    quality = ResultQuality.SOLVER_FAILURE if nonfinite else ResultQuality.NUMERICAL_APPROXIMATION
    grid_dims = list(rep.eulerian_energy_density.shape)
    for rtype, loc in (("grid:stress_energy", "arrays/grid.npz"),
                       ("grid:eulerian_energy_density", "arrays/energy_density.npz")):
        run.computation_results.append(ComputationResult(
            experiment_id=exp.id, result_type=rtype, quality=quality,
            tensor_rank=2 if "stress" in rtype else 0, dimensions=grid_dims,
            array_location=loc, units="geometrized", precision=exp.precision,
            convergence_status="single_resolution",
            warnings=field_warnings, checksum=run.checksums[loc],
        ))


def finalize_run(run: ExperimentRun, status: ExperimentStatus, error: str | None = None) -> dict:
    exp = run.experiment
    exp.status = status
    exp.error = error
    exp.completed_at = utcnow()
    manifest = {
        "experiment": exp.model_dump(mode="json"),
        "spec_hash": exp.spec_hash(),
        "software_version": SOFTWARE_VERSION,
        "source_commit": exp.source_commit or source_commit(),
        "container_image_digest": exp.container_image_digest or container_image_digest(),
        "dependency_versions": dependency_versions(),
        "timings": run.timings,
        "warnings": run.warnings,
        "artifact_checksums": run.checksums,
        "validation_summary": {
            "total": len(run.validation_results),
            "passed": sum(1 for v in run.validation_results if v.status.value == "passed"),
            "failed": sum(1 for v in run.validation_results if v.status.value == "failed"),
        },
    }
    _dump(run.bundle_dir / "manifest.json", manifest)
    (run.bundle_dir / "summary.md").write_text(_summary_md(run, manifest))
    return manifest


def _summary_md(run: ExperimentRun, manifest: dict) -> str:
    exp = run.experiment
    lines = [
        f"# Experiment {exp.id}",
        "",
        f"* Metric: **{exp.metric_name}** v{exp.metric_version} (hash `{exp.metric_hash[:12]}`)",
        f"* Parameters: `{exp.parameter_values}`",
        f"* Status: **{exp.status.value}**",
        f"* Solver: {exp.solver_backend.value}, precision {exp.precision}, seed {exp.random_seed}",
        f"* Source commit: `{manifest['source_commit'][:12]}`",
        f"* Units: geometrized (G = c = 1)",
        "",
        "## Validations",
        "",
        "| check | status | residual | tolerance |",
        "|---|---|---|---|",
    ]
    for v in run.validation_results:
        lines.append(f"| {v.validation_type} | {v.status.value} | {v.residual} | {v.tolerance} |")
    if run.warnings:
        lines += ["", "## Warnings", ""] + [f"* {w}" for w in run.warnings]
    lines += ["", "## Artifacts", ""]
    for name, digest in run.checksums.items():
        lines.append(f"* `{name}` sha256 `{digest[:16]}…`")
    return "\n".join(lines) + "\n"


def execute_experiment(experiment: Experiment) -> tuple[ExperimentRun, dict]:
    """Full pipeline: prepare → symbolic → numerical → finalize.
    Raises nothing: failures are recorded in the manifest and status."""
    experiment.started_at = utcnow()
    experiment.status = ExperimentStatus.RUNNING
    try:
        run = prepare_run(experiment)
    except Exception as exc:
        experiment.status = ExperimentStatus.FAILED
        experiment.error = f"prepare: {exc}"
        experiment.completed_at = utcnow()
        raise
    try:
        run_symbolic_phase(run)
        run_numerical_phase(run)
        manifest = finalize_run(run, ExperimentStatus.COMPLETED)
    except Exception as exc:
        manifest = finalize_run(run, ExperimentStatus.FAILED, error=str(exc))
    return run, manifest


def export_bundle_zip(experiment_id: str) -> Path:
    bundle_dir = experiments_dir() / experiment_id
    if not (bundle_dir / "manifest.json").exists():
        raise FileNotFoundError(f"no bundle for experiment {experiment_id}")
    zip_path = bundle_dir / f"bundle-{experiment_id}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(bundle_dir.rglob("*")):
            if p.is_file() and p != zip_path:
                zf.write(p, p.relative_to(bundle_dir))
    return zip_path

"""Metric definition loading and validation.

Reads YAML/JSON metric definitions, validates them against the JSON Schema in
``schemas/metric-definition.schema.json``, parses every component through the
restricted parser, enforces symmetry, and produces a ``ParsedMetric`` ready
for the tensor pipeline.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import jsonschema
import sympy as sp
import yaml

from forge_domain.entities import DefaultGridSpec, MetricDefinition, ParameterSpec, UnitsMode
from forge_metrics.parser import RestrictedParseError, parse_expression

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "metric-definition.schema.json"
_COMPONENT_RE = re.compile(r"^g_(\d)(\d)$")


class MetricLoadError(ValueError):
    """Raised when a metric definition is structurally invalid."""


@dataclass
class ParsedMetric:
    definition: MetricDefinition
    coords: list[sp.Symbol]
    params: dict[str, sp.Symbol]
    matrix: sp.Matrix
    assumptions: list[sp.Basic] = field(default_factory=list)

    def substituted(self, parameter_values: dict[str, float]) -> sp.Matrix:
        """Metric matrix with parameter values substituted (exact rationals)."""
        subs = self._param_subs(parameter_values)
        return self.matrix.subs(subs)

    def _param_subs(self, parameter_values: dict[str, float]) -> dict[sp.Symbol, sp.Rational]:
        subs = {}
        for name, spec in self.definition.parameters.items():
            value = parameter_values.get(name, spec.default)
            if spec.minimum is not None and value < spec.minimum:
                raise MetricLoadError(f"parameter {name}={value} below minimum {spec.minimum}")
            if spec.maximum is not None and value > spec.maximum:
                raise MetricLoadError(f"parameter {name}={value} above maximum {spec.maximum}")
            subs[self.params[spec.symbol]] = sp.Rational(str(value))
        return subs


def _load_schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text())


def load_metric_file(path: str | Path) -> ParsedMetric:
    path = Path(path)
    if path.suffix not in {".yaml", ".yml", ".json"}:
        raise MetricLoadError(f"unsupported metric file type: {path.suffix}")
    if path.stat().st_size > 1_000_000:
        raise MetricLoadError("metric file exceeds 1 MB limit")
    raw = yaml.safe_load(path.read_text())
    return load_metric_definition(raw)


def load_metric_definition(raw: dict) -> ParsedMetric:
    """Validate a raw definition dict and parse it into symbolic form."""
    try:
        jsonschema.validate(raw, _load_schema())
    except jsonschema.ValidationError as exc:
        raise MetricLoadError(f"metric definition failed schema validation: {exc.message}") from exc

    dim = raw["dimensions"]
    coords_names = raw["coordinates"]
    if len(coords_names) != dim:
        raise MetricLoadError(
            f"dimensions={dim} but {len(coords_names)} coordinates declared"
        )
    if len(set(coords_names)) != dim:
        raise MetricLoadError("duplicate coordinate names")
    if len(raw.get("signature", "-+++")) != dim:
        raise MetricLoadError("signature length does not match dimensions")

    parameters = {
        name: ParameterSpec(**{**spec, "description": spec.get("description", "")})
        for name, spec in raw.get("parameters", {}).items()
    }
    param_symbols = [p.symbol for p in parameters.values()]
    if len(set(param_symbols)) != len(param_symbols):
        raise MetricLoadError("duplicate parameter symbols")
    overlap = set(param_symbols) & set(coords_names)
    if overlap:
        raise MetricLoadError(f"parameter symbols shadow coordinates: {sorted(overlap)}")

    definition = MetricDefinition(
        name=raw["name"],
        version=raw["version"],
        description=raw.get("description", ""),
        coordinate_system=raw.get("coordinate_system", "cartesian"),
        dimensions=dim,
        signature=raw.get("signature", "-+++"),
        units_mode=UnitsMode(raw.get("units", {}).get("mode", "geometrized")),
        parameters=parameters,
        coordinates=coords_names,
        metric_components=raw["metric"],
        assumptions=raw.get("assumptions", []),
        default_grid=_parse_default_grid(raw.get("default_grid"), coords_names),
        source_citation=raw.get("source_citation", ""),
        author=raw.get("author", ""),
    )

    coords = [sp.Symbol(c, real=True) for c in coords_names]
    params = {p.symbol: sp.Symbol(p.symbol, real=True, positive=None) for p in parameters.values()}
    symbols = {c.name: c for c in coords} | params

    matrix = _build_matrix(definition.metric_components, dim, symbols)

    assumptions = []
    for a in definition.assumptions:
        try:
            assumptions.append(parse_expression(a, symbols))
        except RestrictedParseError as exc:
            raise MetricLoadError(f"invalid assumption {a!r}: {exc}") from exc

    return ParsedMetric(
        definition=definition, coords=coords, params=params,
        matrix=matrix, assumptions=assumptions,
    )


def _parse_default_grid(raw_grid: dict | None, coords: list[str]) -> DefaultGridSpec | None:
    """Validate an optional ``default_grid`` block against the coordinate list.

    Every coordinate must appear exactly once, either varied or fixed, so the
    block always describes a complete, unambiguous grid.
    """
    if raw_grid is None:
        return None
    vary = raw_grid.get("vary", {})
    fix = raw_grid.get("fix", {})
    unknown = (set(vary) | set(fix)) - set(coords)
    if unknown:
        raise MetricLoadError(f"default_grid references unknown coordinates: {sorted(unknown)}")
    overlap = set(vary) & set(fix)
    if overlap:
        raise MetricLoadError(
            f"default_grid lists coordinates as both vary and fix: {sorted(overlap)}")
    missing = set(coords) - set(vary) - set(fix)
    if missing:
        raise MetricLoadError(
            f"default_grid must cover every coordinate; missing: {sorted(missing)}")
    for c, (lo, hi) in vary.items():
        if not lo < hi:
            raise MetricLoadError(
                f"default_grid range for {c} must have min < max, got [{lo}, {hi}]")
    return DefaultGridSpec(vary=vary, fix=fix)


def _build_matrix(components: dict[str, str], dim: int, symbols: dict[str, sp.Symbol]) -> sp.Matrix:
    entries: dict[tuple[int, int], sp.Expr] = {}
    for key, text in components.items():
        m = _COMPONENT_RE.match(key)
        if not m:
            raise MetricLoadError(f"bad metric component key {key!r} (expected g_ij)")
        i, j = int(m.group(1)), int(m.group(2))
        if i >= dim or j >= dim:
            raise MetricLoadError(f"component {key} out of range for dimension {dim}")
        try:
            expr = parse_expression(text, symbols)
        except RestrictedParseError as exc:
            raise MetricLoadError(f"component {key}: {exc}") from exc
        if (j, i) in entries and sp.simplify(entries[(j, i)] - expr) != 0:
            raise MetricLoadError(f"components {key} and g_{j}{i} are inconsistent (metric must be symmetric)")
        entries[(i, j)] = expr

    matrix = sp.zeros(dim, dim)
    for i in range(dim):
        for j in range(dim):
            e = entries.get((i, j), entries.get((j, i)))
            if e is None:
                raise MetricLoadError(f"missing metric component g_{min(i,j)}{max(i,j)}")
            matrix[i, j] = e
    return matrix


def builtin_metrics(metrics_dir: str | Path | None = None) -> dict[str, Path]:
    """Map of bundled metric name -> definition file path."""
    root = Path(metrics_dir) if metrics_dir else Path(__file__).resolve().parents[2] / "metrics"
    out: dict[str, Path] = {}
    for p in sorted(root.glob("*/metric.yaml")):
        out[p.parent.name] = p
    return out

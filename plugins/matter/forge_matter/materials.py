"""Versioned material-property database.

Every property carries value, units, condition, source, uncertainty, and
review date. Lookups never invent values: a missing material or property is
an explicit error, not a default.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

_DATA = Path(__file__).parent / "data" / "materials.yaml"


class MaterialError(KeyError):
    pass


@lru_cache(maxsize=1)
def _db() -> dict:
    return yaml.safe_load(_DATA.read_text())


def database_version() -> str:
    return str(_db()["version"])


def list_materials() -> dict:
    return _db()["materials"]


def get_property(material_id: str, prop: str) -> dict:
    materials = _db()["materials"]
    if material_id not in materials:
        raise MaterialError(
            f"unknown material {material_id!r}; known: {sorted(materials)}")
    props = materials[material_id]
    if prop not in props:
        raise MaterialError(
            f"material {material_id!r} has no {prop!r} entry; "
            f"available: {sorted(props)}")
    return props[prop]


def density(material_id: str) -> float:
    return float(get_property(material_id, "density")["value"])


def tensile_strength(material_id: str) -> float:
    return float(get_property(material_id, "tensile_strength")["value"])

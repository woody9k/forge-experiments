"""Gate-2 classical models: Newtonian gravity and weak-field frame dragging.

All SI. All results are C2 (supported analytic approximations) and carry
their model names and validity warnings. Nothing here claims GR fidelity —
these are the fast proxies that let the funnel rank configurations before
Gate 3+ numerical work (not yet implemented).

Frame dragging: Lense–Thirring precession of a gyroscope.
  exterior of a compact rotating source with angular momentum J (z-aligned):
      Ω(r) = G [3(Ĵ·r̂)r̂ − Ĵ] |J| / (c² r³)
  interior of a thin rotating spherical shell (mass M, radius R, angular
  velocity ω):  Ω = 4GMω / (3c²R)   (uniform; e.g. MTW §21.12)
"""

from __future__ import annotations

import math

import numpy as np

from forge_matter.entities import ConfidenceLevel, ObservedEffect

G_SI = 6.674_30e-11
C_LIGHT = 299_792_458.0
MODULE_VERSION = "0.1.0"


def _newtonian_g_component(comp: dict, point: np.ndarray) -> tuple[np.ndarray, list[str]]:
    """Gravitational acceleration vector at `point` from one component.
    Analytic per shape where supported; monopole fallback with warning."""
    warnings: list[str] = []
    pos = np.array(comp["position"], dtype=float)
    rel = point - pos
    r = float(np.linalg.norm(rel))
    m = comp["mass_kg"]
    st = comp["shape_type"]

    if st == "sphere":
        R = comp["shape"]["radius_m"]
        if r >= R:
            return -G_SI * m / r**3 * rel, warnings
        if r == 0:
            return np.zeros(3), warnings
        m_enc = m * (r / R) ** 3
        warnings.append(f"{comp['id']}: interior point; uniform-density enclosed-mass model")
        return -G_SI * m_enc / r**3 * rel, warnings

    if st == "spherical_shell":
        ro = comp["shape"]["outer_radius_m"]
        ri = comp["inner_radius"] if "inner_radius" in comp else ro - comp["shape"]["thickness_m"]
        if r >= ro:
            return -G_SI * m / r**3 * rel, warnings
        if r <= ri:
            return np.zeros(3), warnings  # shell theorem: exact zero inside
        frac = (r**3 - ri**3) / (ro**3 - ri**3)
        warnings.append(f"{comp['id']}: point inside shell wall; partial enclosed mass")
        return -G_SI * m * frac / r**3 * rel, warnings

    if st == "torus":
        # exact on the symmetry axis (ring approximation); monopole elsewhere
        R = comp["shape"]["major_radius_m"]
        axial = rel.copy(); axial[0] = axial[1] = 0.0
        if abs(rel[0]) < 1e-12 * max(R, 1.0) and abs(rel[1]) < 1e-12 * max(R, 1.0):
            z = rel[2]
            gz = -G_SI * m * z / (R**2 + z**2) ** 1.5
            warnings.append(f"{comp['id']}: on-axis thin-ring model (minor radius ignored)")
            return np.array([0.0, 0.0, gz]), warnings
        if r > 3 * comp["shape"]["major_radius_m"]:
            warnings.append(f"{comp['id']}: far-field monopole approximation")
            return -G_SI * m / r**3 * rel, warnings
        warnings.append(
            f"{comp['id']}: off-axis near-field torus gravity unsupported at "
            "Gate 2 — contribution omitted and flagged (needs Gate 3 quadrature)")
        return np.full(3, np.nan), warnings

    if r > 0:
        warnings.append(f"{comp['id']}: monopole approximation for shape {st!r}")
        return -G_SI * m / r**3 * rel, warnings
    return np.full(3, np.nan), warnings


def newtonian_gravity(phenotype: dict) -> list[ObservedEffect]:
    effects = []
    for region in phenotype["observation_regions"]:
        point = np.array(region["position"], dtype=float)
        g = np.zeros(3)
        warnings: list[str] = []
        failed = False
        for comp in phenotype["components"]:
            gi, w = _newtonian_g_component(comp, point)
            warnings.extend(w)
            if not np.all(np.isfinite(gi)):
                failed = True
                continue
            g += gi
        effects.append(ObservedEffect(
            observation_region_id=region["id"],
            effect="newtonian_g_m_s2",
            value=float(np.linalg.norm(g)) if not failed else None,
            units="m/s^2",
            model=f"newtonian_analytic@{MODULE_VERSION}",
            confidence=(ConfidenceLevel.C0_INVALID if failed
                        else ConfidenceLevel.C2_SUPPORTED_APPROXIMATION),
            warnings=warnings + (["one or more contributions unsupported; "
                                  "magnitude not computable"] if failed else []),
        ))
    return effects


def frame_dragging(phenotype: dict) -> list[ObservedEffect]:
    """Lense–Thirring precession rate at each observation region from the
    net z angular momentum of all rotating components."""
    effects = []
    J_net = phenotype["totals"]["angular_momentum_z_kg_m2_s"]
    any_rotating = any(c["motion"] == "rotation" for c in phenotype["components"])
    if not any_rotating:
        return [ObservedEffect(
            observation_region_id=region["id"],
            effect="frame_dragging_rate_rad_s", value=0.0, units="rad/s",
            model=f"no_rotating_sources@{MODULE_VERSION}",
            confidence=ConfidenceLevel.C2_SUPPORTED_APPROXIMATION,
            warnings=[],
        ) for region in phenotype["observation_regions"]]
    for region in phenotype["observation_regions"]:
        point = np.array(region["position"], dtype=float)
        warnings: list[str] = []

        # special case: single thin rotating spherical shell, interior point
        shells = [c for c in phenotype["components"]
                  if c["shape_type"] == "spherical_shell" and c["motion"] == "rotation"]
        others_rotating = [c for c in phenotype["components"]
                           if c["motion"] == "rotation" and c not in shells]
        if len(shells) == 1 and not others_rotating:
            sh = shells[0]
            R = sh["shape"]["outer_radius_m"]
            rel = point - np.array(sh["position"], dtype=float)
            if np.linalg.norm(rel) < R - sh["shape"]["thickness_m"]:
                omega = sh["angular_velocity_rad_s"]
                val = 4 * G_SI * sh["mass_kg"] * omega / (3 * C_LIGHT**2 * R)
                effects.append(ObservedEffect(
                    observation_region_id=region["id"],
                    effect="frame_dragging_rate_rad_s",
                    value=val, units="rad/s",
                    model=f"lense_thirring_shell_interior@{MODULE_VERSION}",
                    confidence=ConfidenceLevel.C2_SUPPORTED_APPROXIMATION,
                    warnings=["thin-shell interior formula 4GMω/(3c²R); "
                              "uniform inside the shell"],
                ))
                continue

        # generic exterior dipole from net J (z-aligned by compiler contract)
        r = float(np.linalg.norm(point))
        if r == 0:
            warnings.append("observation at origin: exterior dipole formula "
                            "invalid; use an interior model or move the region")
            val = None
            conf = ConfidenceLevel.C0_INVALID
        else:
            rhat = point / r
            Jvec = np.array([0.0, 0.0, J_net])
            omega_vec = G_SI * (3 * np.dot(Jvec, rhat) * rhat - Jvec) / (C_LIGHT**2 * r**3)
            val = float(np.linalg.norm(omega_vec))
            conf = ConfidenceLevel.C2_SUPPORTED_APPROXIMATION
            warnings.append("exterior Lense–Thirring dipole from net J; valid "
                            "far from the source distribution")
            max_extent = max((c["shape"].get("outer_radius_m")
                              or c["shape"].get("major_radius_m", 0)
                              or c["shape"].get("radius_m", 0))
                             for c in phenotype["components"]) if phenotype["components"] else 0
            if r < 1.5 * max_extent:
                warnings.append(
                    f"observation radius {r:.3g} m is within 1.5× the source "
                    "extent — dipole approximation degraded")
                conf = ConfidenceLevel.C1_EXPLORATORY_PROXY
        effects.append(ObservedEffect(
            observation_region_id=region["id"],
            effect="frame_dragging_rate_rad_s",
            value=val, units="rad/s",
            model=f"lense_thirring_dipole@{MODULE_VERSION}",
            confidence=conf, warnings=warnings,
        ))
    return effects

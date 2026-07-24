"""Unit conventions.

The pipeline computes in geometrized units (G = c = 1), where
T_{μν} = G_{μν} / 8π.  SI conversion is applied only at presentation /
export time and is always explicit in result metadata.
"""

from __future__ import annotations

C_SI = 299_792_458.0            # m / s (exact)
G_SI = 6.674_30e-11             # m^3 kg^-1 s^-2 (CODATA 2018)
EINSTEIN_FACTOR_SI = C_SI**4 / (8.0 * 3.141592653589793 * G_SI)  # ≈ 4.82e42 kg m / s^2


def stress_energy_si_factor() -> float:
    """Multiply geometrized T_{μν} (= G_{μν}/8π) by 8π·c⁴/(8πG) = c⁴/G ...

    Note: our geometrized stress_energy already includes the 1/8π, so the SI
    energy-density scale factor is c⁴/G divided by 8π times 8π = c⁴/(8πG) per
    unit of G_{μν}.  Concretely: T_SI = G_{μν} · c⁴/(8πG) = stress_energy_geom · c⁴/G.
    """
    return C_SI**4 / G_SI

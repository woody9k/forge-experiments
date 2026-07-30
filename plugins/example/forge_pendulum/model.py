"""The pendulum domain model: pure functions, no platform imports.

Kept deliberately separate from anything Forge-shaped so a reader can see
which parts of a plugin are *domain* and which are *contract*.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict

#: Standard gravity (m/s²).  A domain constant: the platform has no opinion.
G = 9.80665

ENTITIES = ("pendulum_run",)


@dataclass(frozen=True)
class PendulumSpec:
    """What to investigate: a pendulum and how to release it."""

    length_m: float
    initial_angle_deg: float
    damping: float = 0.0          # velocity damping coefficient (1/s)
    duration_s: float = 10.0
    timestep_s: float = 1e-3

    def validate(self) -> None:
        """Fail loudly on physically meaningless input, before integrating."""
        if self.length_m <= 0:
            raise ValueError(f"length must be positive, got {self.length_m}")
        if not 0 < abs(self.initial_angle_deg) <= 170:
            raise ValueError(
                f"initial angle must be within ±170° and non-zero, got "
                f"{self.initial_angle_deg}")
        if self.damping < 0:
            raise ValueError(f"damping cannot be negative, got {self.damping}")
        if self.timestep_s <= 0 or self.timestep_s > 0.05:
            raise ValueError(
                f"timestep must be in (0, 0.05] s for a stable integration, "
                f"got {self.timestep_s}")
        if self.duration_s <= 0:
            raise ValueError(f"duration must be positive, got {self.duration_s}")


def small_angle_period_s(length_m: float) -> float:
    """The known answer: T = 2π√(L/g), exact only as amplitude → 0."""
    return 2 * math.pi * math.sqrt(length_m / G)


SMALL_ANGLE_PERIOD_S = small_angle_period_s


@dataclass
class PendulumResult:
    """What was observed, with its epistemic status attached."""

    measured_period_s: float | None
    small_angle_period_s: float
    relative_deviation: float | None
    swings_measured: int
    max_angle_deg: float
    energy_drift: float
    quality: str                  # exact_analytic | numerical_approximation | unresolved
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def integrate(spec: PendulumSpec) -> PendulumResult:
    """Integrate θ'' = -(g/L)·sin θ − b·θ' and measure the period.

    Velocity-Verlet (symplectic) so the undamped case conserves energy to
    within the timestep's error — which is *reported*, not assumed: a large
    energy drift means the measurement is not trustworthy and the result says
    so rather than quietly returning a number.
    """
    spec.validate()
    theta = math.radians(spec.initial_angle_deg)
    omega = 0.0
    dt = spec.timestep_s
    k = G / spec.length_m

    def accel(th: float, om: float) -> float:
        return -k * math.sin(th) - spec.damping * om

    def energy(th: float, om: float) -> float:
        # per unit mass: ½(Lω)² + gL(1 − cos θ)
        return 0.5 * (spec.length_m * om) ** 2 + G * spec.length_m * (1 - math.cos(th))

    e0 = energy(theta, omega)
    e_min = e_max = e0
    max_angle = abs(theta)
    zero_crossing_times: list[float] = []
    warnings: list[str] = []

    steps = int(spec.duration_s / dt)
    t = 0.0
    for _ in range(steps):
        a = accel(theta, omega)
        theta_next = theta + omega * dt + 0.5 * a * dt * dt
        a_next = accel(theta_next, omega + a * dt)
        omega_next = omega + 0.5 * (a + a_next) * dt

        # a downward zero crossing marks half a period; interpolate the instant
        if theta > 0 >= theta_next or theta < 0 <= theta_next:
            frac = theta / (theta - theta_next) if theta != theta_next else 0.0
            zero_crossing_times.append(t + frac * dt)

        theta, omega, t = theta_next, omega_next, t + dt
        max_angle = max(max_angle, abs(theta))
        if spec.damping == 0:
            e = energy(theta, omega)
            e_min, e_max = min(e_min, e), max(e_max, e)

    drift = 0.0 if spec.damping or e0 == 0 else (e_max - e_min) / e0
    if drift > 1e-3:
        warnings.append(
            f"energy drifted {drift:.2e} of its initial value; reduce the "
            f"timestep before trusting the measured period")

    half_periods = [b - a for a, b in
                    zip(zero_crossing_times, zero_crossing_times[1:])]
    if len(half_periods) < 2:
        warnings.append(
            f"only {len(zero_crossing_times)} zero crossing(s) in "
            f"{spec.duration_s} s — too few to measure a period; run longer")
        return PendulumResult(
            measured_period_s=None,
            small_angle_period_s=small_angle_period_s(spec.length_m),
            relative_deviation=None, swings_measured=len(zero_crossing_times),
            max_angle_deg=math.degrees(max_angle), energy_drift=drift,
            quality="unresolved", warnings=warnings)

    measured = 2 * (sum(half_periods) / len(half_periods))
    ideal = small_angle_period_s(spec.length_m)
    deviation = (measured - ideal) / ideal
    if abs(spec.initial_angle_deg) > 10 and deviation < 0:
        warnings.append(
            "a large-amplitude pendulum should swing *slower* than the "
            "small-angle formula, not faster — check the integration")
    return PendulumResult(
        measured_period_s=measured,
        small_angle_period_s=ideal,
        relative_deviation=deviation,
        swings_measured=len(zero_crossing_times),
        max_angle_deg=math.degrees(max_angle),
        energy_drift=drift,
        quality="numerical_approximation",
        warnings=warnings)

# Pendulum-lab domain pack

Owned by the pendulum example plugin; composed into SAGE role prompts by the
platform. Domain expertise, not a role: the role's own rules always win.

## Terminology

- A **run** is one integration of a pendulum's motion from a released angle,
  identified by a run id. Its **spec** is length, initial angle, damping,
  duration and timestep.
- The **small-angle period** is the closed form `T = 2π√(L/g)`. It is exact
  only in the limit of zero amplitude.
- **Deviation** is the measured period's relative difference from that closed
  form. It is expected to be *positive* and to grow with amplitude: a real
  pendulum swings slower than the linear approximation predicts.

## Procedures

- `predict_pendulum_period` gives the closed form with no experiment; prefer
  it over deriving the formula, and cite it as the baseline.
- `run_pendulum_experiment` submits one run. Amplitudes above 5° are outside
  the small-angle regime, and the platform records the known-answer check as
  *inapplicable* rather than passing or failing it — do not read that as
  agreement.
- A run with fewer than two zero crossings measures nothing; lengthen
  `duration_s` rather than reinterpreting the result.

## Interpretation

- Energy drift above 1e-3 of the initial value means the integration, not the
  pendulum, is being measured; reduce `timestep_s` and rerun.
- A *negative* deviation at large amplitude is physically wrong and indicates
  a defect, not a discovery.
- Damping suppresses the amplitude over time, so a damped run's measured
  period drifts across the window; say so when comparing damped runs.

"""Pendulum Lab — the reference Forge plugin.

A deliberately small investigative domain: a damped pendulum whose period
can be predicted, measured, and checked against a known answer.  It exists
to be *read*, so it uses no physics beyond secondary-school mechanics and no
dependency beyond the standard library.

It exercises every contribution point a plugin can use, so it doubles as the
worked example for the authoring guide:

| contribution | what it looks like here |
|---|---|
| API router | `/api/v1/pendulum/*` — define a pendulum, run it, read results |
| SAGE tools | list/get/predict (read) and `run_pendulum_experiment` (write) |
| selftest suite | proves a worker can integrate the equation of motion |
| queue task type | the run executed on the `numerical` queue |
| persistence metadata | `pendulum_runs`, owned by this plugin |
| SAGE domain pack | terminology and interpretation guidance for the roles |
| MCP tools | the same reads over the MCP surface |
| UI module | an Experiments section with a form and a results table |

The known answer it validates against is the small-angle period,
``T = 2*pi*sqrt(L/g)``, which a numerical integration of the full nonlinear
equation should approach as the amplitude shrinks.  Getting that comparison
*honestly* — reporting the deviation rather than hiding it — is the point of
the example.
"""

__all__ = ["ENTITIES", "SMALL_ANGLE_PERIOD_S"]

from forge_pendulum.model import ENTITIES, SMALL_ANGLE_PERIOD_S

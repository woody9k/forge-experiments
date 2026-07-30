"""SAGE tools this plugin contributes.

Every tool is (spec, handler).  The spec declares who may call it and at
what risk class; the platform's policy layer enforces both — a plugin can
add capability, never widen policy.  Handlers receive the program and the
model's arguments, and must treat those arguments as untrusted: validate
ids and values, fail loudly, never interpolate them into anything.
"""

from __future__ import annotations

from forge_pendulum.app import runner, store
from forge_pendulum.model import small_angle_period_s
from forge_sage import Role
from forge_sage.policies import RiskClass
from forge_sage.tools import read_tool, write_tool

_ALL = set(Role)


class PendulumToolError(RuntimeError):
    """A permitted tool failed while executing."""


def _list_pendulum_runs(program, args):
    return {"runs": store.list_runs(limit=int(args.get("limit", 20)))}


def _get_pendulum_run(program, args):
    run = store.load_run(str(args["run_id"]))
    if run is None:
        raise PendulumToolError(f"unknown pendulum run {args['run_id']!r}")
    return run


def _predict_pendulum_period(program, args):
    """A read tool that computes rather than fetches: the closed form is
    knowledge the domain has, so the model does not have to derive it."""
    try:
        length = float(args["length_m"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PendulumToolError(f"length_m must be a number: {exc}") from exc
    if length <= 0:
        raise PendulumToolError(f"length must be positive, got {length}")
    return {"length_m": length,
            "small_angle_period_s": small_angle_period_s(length),
            "quality": "exact_analytic"}


def _run_pendulum_experiment(program, args):
    """The write tool: submit an experiment, then report what Forge observed.

    Note what it does *not* do: it never judges its own result. It returns
    the validation record the pipeline produced, and the platform's evidence
    layer decides what that is worth.
    """
    spec = {
        "length_m": float(args.get("length_m", 1.0)),
        "initial_angle_deg": float(args.get("initial_angle_deg", 5.0)),
        "damping": float(args.get("damping", 0.0)),
        "duration_s": float(args.get("duration_s", 20.0)),
        "timestep_s": float(args.get("timestep_s", 1e-3)),
    }
    reserved = args.get("run_id")
    run = runner.execute(spec, str(reserved) if reserved else None)
    if run["status"] != "completed":
        raise PendulumToolError(
            f"pendulum run {run['id']} failed: {run.get('error')}")
    return {"run_id": run["id"], "status": run["status"],
            "result": run["result"], "validation": run["validation"],
            "bundle": run.get("bundle")}


TOOLS = [
    (read_tool("list_pendulum_runs", _ALL, "List pendulum experiment runs."),
     _list_pendulum_runs),
    (read_tool("get_pendulum_run", _ALL, "Fetch one pendulum run with its "
                                        "result and validation."),
     _get_pendulum_run),
    (read_tool("predict_pendulum_period", _ALL,
               "Closed-form small-angle period for a given length."),
     _predict_pendulum_period),
    (write_tool("run_pendulum_experiment", RiskClass.R2_BOUNDED_EXPERIMENT,
                {Role.DESIGNER},
                "Run one pendulum experiment and return Forge's validation."),
     _run_pendulum_experiment),
]

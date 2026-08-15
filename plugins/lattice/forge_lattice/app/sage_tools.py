from forge_lattice.model import LatticeInputError, simulate_stack
from forge_sage import Role
from forge_sage.policies import RiskClass
from forge_sage.tools import write_tool


def _simulate(_program, args):
    try:
        return simulate_stack(args)
    except LatticeInputError as exc:
        raise RuntimeError(f"invalid lattice experiment: {exc}") from exc


TOOLS = [(write_tool(
    "simulate_lattice_stack", RiskClass.R2_BOUNDED_EXPERIMENT, {Role.DESIGNER},
    "Run the bounded 1D Mg-Zn/Bi layered-stack EM model. Conventional EM outputs and speculative gravity scales are explicitly separated."), _simulate)]

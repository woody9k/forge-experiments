from forge_lattice.model import LatticeInputError, simulate_stack
from forge_sage import Role
from forge_sage.policies import RiskClass
from forge_sage.tools import write_tool


def _simulate(_program, args):
    # Resolved per call, not bound at import.  Two reasons, and the second is
    # the one that bites:
    #
    # 1. ToolExecutionError specifically, never a bare RuntimeError.
    #    ``sage_tools.call_tool`` catches only ToolExecutionError, and it
    #    writes the failed-attempt audit row *inside* that handler, so any
    #    other exception escapes and leaves **no** row — breaking the rule
    #    that every tool attempt appends exactly one ``sage_tool_calls``
    #    record.
    # 2. A module-level ``from apps.coordinator.sage_tools import
    #    ToolExecutionError`` binds the class object that existed when this
    #    module was first imported.  The platform's fresh-environment pattern
    #    purges ``sys.modules["apps.*"]`` and re-imports, which mints a *new*
    #    class; a plugin module that was not purged alongside keeps raising
    #    the stale one, and ``call_tool``'s ``except`` — holding the new one —
    #    stops matching.  The failure is invisible until it matters: the tool
    #    still errors, and the audit row silently stops being written.
    #    Geometry and matter avoid this only because the loop fixtures happen
    #    to purge their app modules by name; resolving here needs no such
    #    coordination.
    from apps.coordinator.sage_tools import ToolExecutionError

    try:
        return simulate_stack(args)
    except LatticeInputError as exc:
        raise ToolExecutionError(f"invalid lattice experiment: {exc}") from exc


TOOLS = [(write_tool(
    "simulate_lattice_stack", RiskClass.R2_BOUNDED_EXPERIMENT, {Role.DESIGNER},
    "Run the bounded 1D Mg-Zn/Bi layered-stack EM model. Conventional EM outputs and speculative gravity scales are explicitly separated."), _simulate)]

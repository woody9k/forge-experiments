"""_compat_ shim: the restricted expression parser moved to
``forge_sdk.expressions`` (platform-split Phase 2, decision D3 — it is a
security boundary shared by the geometry and matter domains, so it lives in
the SDK under platform review).  This re-export keeps existing imports
working until the Phase 5 cleanup; new code should import from
``forge_sdk.expressions`` directly.
"""

from forge_sdk.expressions import (
    ALLOWED_CONSTANTS,
    ALLOWED_FUNCTIONS,
    MAX_EXPRESSION_LENGTH,
    RestrictedParseError,
    parse_expression,
)

__all__ = [
    "ALLOWED_CONSTANTS",
    "ALLOWED_FUNCTIONS",
    "MAX_EXPRESSION_LENGTH",
    "RestrictedParseError",
    "parse_expression",
]

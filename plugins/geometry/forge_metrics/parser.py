"""Restricted symbolic expression parser.

Metric definition files are untrusted input.  This module is the only place
where strings from metric files become SymPy expressions, and it enforces:

* a token-level allowlist (checked with Python's ``tokenize`` before SymPy
  ever sees the string) — attribute access, subscripts, assignments, lambdas,
  string literals, and every name outside the declared symbol set are
  rejected;
* an expression size limit;
* a restricted SymPy parse namespace (no implicit multiplication, empty
  global namespace, allowlisted functions only).

SymPy's ``parse_expr`` ultimately calls ``eval`` on a transformed token
stream, so the pre-tokenization filter is the load-bearing defense: by the
time ``parse_expr`` runs, the string can only contain allowlisted names,
numeric literals, arithmetic operators, parentheses, and commas.
"""

from __future__ import annotations

import io
import token as tk
import tokenize

import sympy as sp
from sympy.parsing.sympy_parser import parse_expr, standard_transformations

MAX_EXPRESSION_LENGTH = 20_000

#: Functions metric authors may use.  Extending this list is a reviewed change.
ALLOWED_FUNCTIONS: dict[str, sp.Function] = {
    "sin": sp.sin, "cos": sp.cos, "tan": sp.tan,
    "asin": sp.asin, "acos": sp.acos, "atan": sp.atan, "atan2": sp.atan2,
    "sinh": sp.sinh, "cosh": sp.cosh, "tanh": sp.tanh,
    "exp": sp.exp, "log": sp.log, "sqrt": sp.sqrt,
    "Abs": sp.Abs, "abs": sp.Abs, "sign": sp.sign,
    "Min": sp.Min, "Max": sp.Max,
    "Rational": sp.Rational,
}

ALLOWED_CONSTANTS: dict[str, sp.Expr] = {
    "pi": sp.pi,
}

#: Operator tokens permitted in expressions (comparisons included so the same
#: parser can read assumption strings like "R > 0").
_ALLOWED_OPS = {
    "+", "-", "*", "/", "**", "(", ")", ",",
    "<", ">", "<=", ">=",
}

_ALLOWED_TOKEN_TYPES = {
    tk.NUMBER, tk.NEWLINE, tk.NL, tk.ENDMARKER, tk.ENCODING, tk.INDENT, tk.DEDENT,
}


class RestrictedParseError(ValueError):
    """Raised when an expression violates the restricted grammar."""


def _validate_tokens(text: str, allowed_names: set[str]) -> None:
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except tokenize.TokenError as exc:
        raise RestrictedParseError(f"untokenizable expression: {exc}") from exc

    for t in tokens:
        if t.type == tk.NAME:
            if t.string not in allowed_names:
                raise RestrictedParseError(
                    f"name {t.string!r} is not an allowed symbol, parameter, or function"
                )
        elif t.type == tk.OP:
            if t.string not in _ALLOWED_OPS:
                raise RestrictedParseError(f"operator {t.string!r} is not allowed")
        elif t.type in _ALLOWED_TOKEN_TYPES:
            continue
        else:
            raise RestrictedParseError(
                f"token {tokenize.tok_name[t.type]} ({t.string!r}) is not allowed"
            )


def parse_expression(
    text: str,
    symbols: dict[str, sp.Symbol],
) -> sp.Expr:
    """Parse ``text`` into a SymPy expression using only declared ``symbols``
    plus the function/constant allowlists.  Raises ``RestrictedParseError``
    on any violation."""
    if not isinstance(text, str):
        raise RestrictedParseError(f"expression must be a string, got {type(text).__name__}")
    if len(text) > MAX_EXPRESSION_LENGTH:
        raise RestrictedParseError(
            f"expression length {len(text)} exceeds limit {MAX_EXPRESSION_LENGTH}"
        )
    if not text.strip():
        raise RestrictedParseError("empty expression")

    allowed_names = set(symbols) | set(ALLOWED_FUNCTIONS) | set(ALLOWED_CONSTANTS)
    _validate_tokens(text, allowed_names)

    local_dict: dict[str, object] = {**ALLOWED_FUNCTIONS, **ALLOWED_CONSTANTS, **symbols}
    try:
        # parse_expr's number transformation emits Integer(...)/Float(...)
        # constructor calls; those names must resolve in the eval namespace.
        expr = parse_expr(
            text,
            local_dict=local_dict,
            global_dict={"Integer": sp.Integer, "Float": sp.Float, "Rational": sp.Rational},
            transformations=standard_transformations,
            evaluate=True,
        )
    except RecursionError as exc:
        raise RestrictedParseError("expression exceeds recursion limits") from exc
    except Exception as exc:  # sympy raises many exception types on bad input
        raise RestrictedParseError(f"failed to parse expression: {exc}") from exc

    if not isinstance(expr, (sp.Expr, sp.logic.boolalg.Boolean)):
        raise RestrictedParseError(f"expression parsed to unsupported object {type(expr)}")
    return expr

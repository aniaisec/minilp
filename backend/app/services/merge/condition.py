"""A tiny, safe expression evaluator for pipeline stage conditions (§7.2).

§7.2 writes routing conditions as strings::

    { "stage": "auto_finalize", "if": "consensus >= 0.9 && entropy <= 0.3" }

That string arrives from a project's stored ``pipeline`` — i.e. from the network,
from an imported marketplace bundle (M10), from whoever can PATCH a project. It
is therefore emphatically *not* something to hand to ``eval``. This module parses
a deliberately small grammar and evaluates it against a fixed variable
environment:

    expr    := or
    or      := and  ( ("||" | "or")  and  )*
    and     := cmp  ( ("&&" | "and") cmp  )*
    cmp     := unary ( ("<=" | ">=" | "==" | "!=" | "<" | ">") unary )?
    unary   := ("!" | "not") unary | primary
    primary := number | ident | "true" | "false" | "(" expr ")"

No function calls, no attribute access, no indexing, no assignment — there is
nothing in the grammar to escape *from*. An unknown identifier is an error rather
than a silent ``false``, because a condition that quietly never fires is the
worst possible failure mode for a routing rule: units would pile up in review
with no indication why.

Conditions are validated at save time (``check_condition``), so a typo is a 422
on the project edit rather than a surprise three thousand units later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

__all__ = ["ConditionError", "check_condition", "evaluate_condition"]


class ConditionError(ValueError):
    """A condition that cannot be parsed, or references an unknown variable."""


_TOKEN_RE = re.compile(
    r"""
    \s*(?:
        (?P<number>\d+(?:\.\d+)?)
      | (?P<op><=|>=|==|!=|&&|\|\||<|>|!|\(|\))
      | (?P<ident>[A-Za-z_][A-Za-z0-9_.]*)
    )
    """,
    re.VERBOSE,
)

_WORD_OPS = {"and": "&&", "or": "||", "not": "!"}
_CONSTANTS = {"true": True, "false": False}


@dataclass(frozen=True)
class _Token:
    kind: str  # number | op | ident
    text: str
    pos: int


def _tokenize(source: str) -> list[_Token]:
    tokens: list[_Token] = []
    index = 0
    while index < len(source):
        if source[index].isspace():
            index += 1
            continue
        match = _TOKEN_RE.match(source, index)
        if match is None or match.end() == index:
            raise ConditionError(f"unexpected character {source[index]!r} at position {index}")
        for kind in ("number", "op", "ident"):
            text = match.group(kind)
            if text is not None:
                if kind == "ident" and text.lower() in _WORD_OPS:
                    tokens.append(_Token("op", _WORD_OPS[text.lower()], index))
                else:
                    tokens.append(_Token(kind, text, index))
                break
        index = match.end()
    return tokens


class _Parser:
    """Recursive-descent parser that evaluates as it goes.

    Evaluating during the parse keeps this to one pass and ~60 lines; there is no
    AST to reuse because a condition is read once per unit and the environment
    changes every time.
    """

    def __init__(self, tokens: list[_Token], env: dict[str, Any]) -> None:
        self.tokens = tokens
        self.env = env
        self.i = 0

    def peek(self) -> _Token | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def accept(self, *texts: str) -> _Token | None:
        token = self.peek()
        if token is not None and token.kind == "op" and token.text in texts:
            self.i += 1
            return token
        return None

    # --- grammar ----------------------------------------------------------

    def parse(self) -> Any:
        value = self.or_expr()
        if self.i != len(self.tokens):
            leftover = self.tokens[self.i]
            raise ConditionError(f"unexpected {leftover.text!r} at position {leftover.pos}")
        return value

    def or_expr(self) -> Any:
        value = self.and_expr()
        while self.accept("||"):
            # No short-circuit: the right-hand side is evaluated so that a typo'd
            # variable in it still raises instead of hiding behind a true left.
            value = _truthy(self.and_expr()) or _truthy(value)
        return value

    def and_expr(self) -> Any:
        value = self.cmp_expr()
        while self.accept("&&"):
            value = _truthy(self.cmp_expr()) and _truthy(value)
        return value

    def cmp_expr(self) -> Any:
        left = self.unary()
        token = self.accept("<=", ">=", "==", "!=", "<", ">")
        if token is None:
            return left
        right = self.unary()
        return _compare(token.text, left, right)

    def unary(self) -> Any:
        if self.accept("!"):
            return not _truthy(self.unary())
        return self.primary()

    def primary(self) -> Any:
        token = self.peek()
        if token is None:
            raise ConditionError("unexpected end of condition")
        if token.kind == "op" and token.text == "(":
            self.i += 1
            value = self.or_expr()
            if not self.accept(")"):
                raise ConditionError("missing closing ')'")
            return value
        self.i += 1
        if token.kind == "number":
            return float(token.text)
        if token.kind == "ident":
            key = token.text.lower()
            if key in _CONSTANTS:
                return _CONSTANTS[key]
            if token.text not in self.env:
                known = ", ".join(sorted(self.env))
                raise ConditionError(f"unknown variable '{token.text}' (available: {known})")
            return self.env[token.text]
        raise ConditionError(f"unexpected {token.text!r} at position {token.pos}")


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value != 0
    return bool(value)


def _compare(op: str, left: Any, right: Any) -> bool:
    if op == "==":
        return _coerce(left) == _coerce(right)
    if op == "!=":
        return _coerce(left) != _coerce(right)
    try:
        left_n, right_n = float(left), float(right)
    except (TypeError, ValueError) as e:
        raise ConditionError(f"cannot compare {left!r} {op} {right!r}") from e
    if op == "<":
        return left_n < right_n
    if op == ">":
        return left_n > right_n
    if op == "<=":
        return left_n <= right_n
    return left_n >= right_n


def _coerce(value: Any) -> Any:
    """Make ``agreed == true`` and ``agreed == 1`` mean the same thing."""
    return float(value) if isinstance(value, bool) else value


def evaluate_condition(source: str, env: dict[str, Any]) -> bool:
    """Evaluate ``source`` against ``env``; raises ``ConditionError`` on anything odd."""
    if source is None:
        return True
    text = str(source).strip()
    if not text:
        return True
    tokens = _tokenize(text)
    if not tokens:
        raise ConditionError("empty condition")
    return _truthy(_Parser(tokens, env).parse())


def check_condition(source: str, variables: set[str]) -> None:
    """Validate a condition at save time against the *names* it may reference.

    Uses a sentinel environment of zeros so the parse and the name resolution are
    exercised without needing a real unit.
    """
    evaluate_condition(source, dict.fromkeys(variables, 0.0))

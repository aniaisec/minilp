"""Parse a judge's reply into a raw answer dict, confidence and reasoning (§7.1).

Two principles, both learned the expensive way from `canonical.py`:

**Forgiving about input.** Models wrap JSON in fences, prefix it with "Sure!",
or answer with the bare object. All three are the same answer and all three are
accepted. What is *not* accepted is guessing: an unparseable reply raises, the
orchestrator releases the slot, and the unit stays open for someone else. A judge
whose output we could not read must not silently become a label.

**Strict about output.** The parsed answers go through the exact same path a
human submission does — ``submit_label`` recanonicalizes them server-side from
``raw`` (§2.6). This module therefore does *no* canonicalization: it produces
``raw``, the same shape a browser posts, and lets the one authoritative
canonicalizer do its job. Two canonicalizers is one too many.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

_FENCE_RE = re.compile(r"```(?:json)?\s*(?P<body>.*?)```", re.S | re.I)


class ParseError(Exception):
    """The reply could not be read as an answer."""


@dataclass
class ParsedAnswer:
    raw: dict[str, Any]
    confidence: float | None = None
    reasoning: str | None = None
    #  Fields the judge answered that the template does not declare, and required
    #  fields it omitted. Recorded rather than fatal: a missing optional field is
    #  fine, and an extra key is noise, but both are worth seeing in a run report.
    unknown_fields: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)


def _extract_json(text: str) -> dict[str, Any]:
    """Pull the answer object out of whatever the model wrapped it in."""
    if not text or not text.strip():
        raise ParseError("empty response")
    candidates: list[str] = []
    for match in _FENCE_RE.finditer(text):
        candidates.append(match.group("body"))
    candidates.append(text)
    # Last resort: the outermost brace-balanced span.
    start, depth = text.find("{"), 0
    if start >= 0:
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start : i + 1])
                    break
    for candidate in candidates:
        try:
            parsed = json.loads(candidate.strip())
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ParseError(f"no JSON object found in response: {text[:200]!r}")


def _as_confidence(value: Any) -> float | None:
    """Accept ``0.85``, ``85``, or ``"85%"`` — clamp to [0, 1], None if unreadable.

    Anything above 1 is read as a percentage. That is a guess, but it is the only
    guess consistent with both conventions, and the alternative (storing 85.0 in a
    field every downstream weight treats as a probability) would poison the merge
    weights in M8 rather than merely being imprecise here.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            value = float(value.strip().rstrip("%").strip())
        except ValueError:
            return None
    if not isinstance(value, int | float):
        return None
    number = float(value)
    if number > 1.0:
        number /= 100.0
    return max(0.0, min(1.0, number))


def parse_response(
    text: str,
    field_ids: list[str] | None = None,
    *,
    required_ids: list[str] | None = None,
) -> ParsedAnswer:
    """Parse a provider reply. Raises ``ParseError`` when there is no answer in it."""
    body = _extract_json(text)

    answers = body.get("answers")
    if not isinstance(answers, dict):
        # Some models skip the envelope and answer with the fields directly.
        reserved = {"answers", "confidence", "reasoning"}
        answers = {k: v for k, v in body.items() if k not in reserved}
    if not answers:
        raise ParseError("response contained no answers")

    known = set(field_ids or [])
    raw = {k: v for k, v in answers.items() if not known or k in known}
    unknown = sorted(k for k in answers if known and k not in known)
    missing = [fid for fid in (required_ids or []) if fid not in raw]
    if not raw:
        raise ParseError(f"response answered none of the template's fields (got {sorted(answers)})")

    reasoning = body.get("reasoning")
    return ParsedAnswer(
        raw=raw,
        confidence=_as_confidence(body.get("confidence")),
        reasoning=str(reasoning) if isinstance(reasoning, str | int | float) else None,
        unknown_fields=unknown,
        missing_fields=missing,
    )

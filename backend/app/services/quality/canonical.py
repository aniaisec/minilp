"""Server-side canonicalization: raw answer → canonical value (§2.3, §2.6, §2.8).

M3 canonicalized in the browser and posted both ``raw`` and ``value``. From M4 the
backend is authoritative: gold grading, agreement and merge all read ``value``, so a
client that computes it wrongly (or maliciously) would corrupt every quality signal
downstream. The client still sends ``value`` — it is now advisory and only used for
input types this module declines to canonicalize.

Mirrors ``frontend/src/render/canonical.ts``; the two are kept in sync by the
shared gallery fixtures (a template that canonicalizes differently on the two
sides shows up as a gold/agreement discrepancy in tests).
"""

from __future__ import annotations

from typing import Any

OTHER_PREFIX = "other:"

# Positional option labels that a variant maps onto items (§2.7).
_LEFT_LABELS = {"left", "a", "first"}
_RIGHT_LABELS = {"right", "b", "second"}


def _strip_other(value: Any) -> Any:
    """``"other:capybara"`` → ``"capybara"`` (the escape hatch, §2.3)."""
    if isinstance(value, str) and value.startswith(OTHER_PREFIX):
        return value[len(OTHER_PREFIX) :]
    return value


def positional_variant(
    template_schema: dict[str, Any], variant: dict[str, Any] | None
) -> str | None:
    """The variant string (e.g. ``"BA"``) when the template declares one, else None."""
    variants = template_schema.get("variants")
    if not variants or not variant:
        return None
    dimension = variants.get("dimension")
    if not dimension:
        return None
    value = variant.get(dimension)
    return value if isinstance(value, str) else None


def canonicalize_positional(label: Any, variant: str | None) -> Any:
    """Map a side clicked onto the item shown there.

    Under ``panel_order="BA"`` the left panel holds item B, so a "Left" click
    canonicalizes to ``"B"``. Ties and unrecognized labels pass through. This is
    what makes position bias measurable (§9): ``raw`` keeps the side, ``value``
    keeps the item.
    """
    if not isinstance(label, str) or not variant:
        return label
    key = label.strip().lower()
    if key in _LEFT_LABELS:
        return variant[0]
    if key in _RIGHT_LABELS:
        return variant[-1]
    return label


# --- M6 value-shape canonicalizers (§2.3, §2.6 step 3) ----------------------
#
# Each new input type declares a value shape; these functions are the "optional
# canonicalizer" of the extensibility contract. They are deliberately forgiving
# about what arrives (an HTML number field yields a string, a checkbox yields
# "true") and strict about what is stored, because gold grading and agreement
# only ever read the canonical side.

_TRUE_TOKENS = {"true", "yes", "y", "1", "on"}
_FALSE_TOKENS = {"false", "no", "n", "0", "off"}


def _to_bool(raw: Any) -> Any:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int | float):
        return bool(raw)
    if isinstance(raw, str):
        token = raw.strip().lower()
        if token in _TRUE_TOKENS:
            return True
        if token in _FALSE_TOKENS:
            return False
    return raw  # unrecognized → pass through; a gold will simply not match


def _to_number(raw: Any, *, integral: bool = False) -> Any:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int | float):
        return int(raw) if integral else raw
    if isinstance(raw, str) and raw.strip():
        try:
            number = float(raw.strip())
        except ValueError:
            return raw
        if integral or number.is_integer():
            return int(number)
        return number
    return raw


def _to_tags(raw: Any) -> Any:
    """Free-form tag entry → a de-duplicated, trimmed, lower-cased string array.

    Case- and whitespace-folding is what makes tags comparable at all: without
    it "Spam", "spam " and "spam" are three different labels and every agreement
    metric over the key is noise.
    """
    items: list[Any]
    if isinstance(raw, str):
        items = raw.split(",")
    elif isinstance(raw, list | tuple):
        items = list(raw)
    else:
        return raw
    out: list[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        tag = " ".join(item.strip().lower().split())
        if tag and tag not in out:
            out.append(tag)
    return out


def _to_string_list(raw: Any) -> Any:
    """``ranking`` — an ordered array; order is the answer, so nothing is sorted."""
    if isinstance(raw, list | tuple):
        return [v for v in raw if isinstance(v, str)]
    return raw


_BY_TYPE = {
    "boolean": _to_bool,
    "number": _to_number,
    "slider": _to_number,
    "rating": lambda raw: _to_number(raw, integral=True),
    "likert": lambda raw: _to_number(raw, integral=True),
    "tags": _to_tags,
    "ranking": _to_string_list,
}


def canonicalize_input(field: dict[str, Any], raw: Any, *, variant_str: str | None) -> Any:
    """Canonicalize one input's raw answer."""
    itype = field.get("type")
    if itype == "choice_buttons" and variant_str:
        return canonicalize_positional(raw, variant_str)
    if field.get("allow_other"):
        if isinstance(raw, list):
            return [_strip_other(v) for v in raw]
        return _strip_other(raw)
    converter = _BY_TYPE.get(itype)
    if converter is not None:
        return converter(raw)
    return raw


def canonicalize(
    template_schema: dict[str, Any],
    raw: dict[str, Any],
    variant: dict[str, Any] | None,
) -> dict[str, Any]:
    """Canonicalize a whole submission. Unknown keys pass through untouched."""
    variant_str = positional_variant(template_schema, variant)
    by_id = {f["id"]: f for f in template_schema.get("inputs", []) if "id" in f}
    out: dict[str, Any] = {}
    for key, value in raw.items():
        field = by_id.get(key)
        out[key] = canonicalize_input(field, value, variant_str=variant_str) if field else value
    return out

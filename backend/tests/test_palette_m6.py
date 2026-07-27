"""M6 expanded field palette (§2.1, §2.3, §2.6) — validation, hotkeys, values.

Every type the visual builder can drop onto a canvas has to survive the same
three gates the v1 types do: it validates (or fails with a readable reason), it
gets a sensible hotkey story, and its raw answer canonicalizes to the declared
value shape. Pure — no database.
"""

import pytest

from app.services.quality.canonical import canonicalize
from app.services.quality.matching import MatchRule, rule_for, values_match
from app.services.templates.hotkeys import assign_hotkeys
from app.services.templates.spec import M6_INPUT_TYPES, VALUE_SHAPES
from app.services.templates.validation import TemplateValidationError, validate_template
from app.services.templates.versioning import is_schema_affecting


def tmpl(*inputs, **extra):
    return {"name": "t", "display": [], "inputs": list(inputs), **extra}


def errors_for(schema) -> list[str]:
    with pytest.raises(TemplateValidationError) as exc:
        validate_template(schema)
    return exc.value.errors


# --- every new type is declared end to end ----------------------------------


def test_every_m6_type_has_a_value_shape() -> None:
    """§2.6 step 1: a type without a declared value shape can't be exported."""
    for itype in M6_INPUT_TYPES:
        assert itype in VALUE_SHAPES, f"{itype} has no declared value shape"


VALID_BY_TYPE = {
    "number": {"id": "n", "type": "number", "min": 0, "max": 10, "step": 0.5},
    "select": {"id": "s", "type": "select", "options": ["a", "b", "c"]},
    "multiselect": {"id": "m", "type": "multiselect", "options": ["a", "b"]},
    "boolean": {"id": "b", "type": "boolean", "label": "Is it spam?"},
    "rating": {"id": "r", "type": "rating", "scale": {"min": 1, "max": 5}},
    "slider": {"id": "sl", "type": "slider", "min": 0, "max": 1, "step": 0.1},
    "tags": {"id": "t", "type": "tags", "label": "Topics"},
    "ranking": {"id": "rk", "type": "ranking", "options": ["a", "b", "c"]},
    "date": {"id": "d", "type": "date"},
    "datetime": {"id": "dt", "type": "datetime"},
}


@pytest.mark.parametrize("itype", M6_INPUT_TYPES)
def test_each_new_type_validates_on_its_own(itype: str) -> None:
    validate_template(tmpl(VALID_BY_TYPE[itype]))


def test_all_new_types_validate_together() -> None:
    """A builder canvas holding one of everything is still a legal template."""
    validate_template(tmpl(*VALID_BY_TYPE.values()))


# --- per-type validation rules ----------------------------------------------


def test_select_needs_at_least_two_options() -> None:
    assert any(
        "at least 2 options" in e
        for e in errors_for(tmpl({"id": "s", "type": "select", "options": ["only"]}))
    )


def test_boolean_must_not_declare_options() -> None:
    errs = errors_for(tmpl({"id": "b", "type": "boolean", "options": ["y", "n"]}))
    assert any("must not declare options" in e for e in errs)


def test_slider_requires_bounds() -> None:
    errs = errors_for(tmpl({"id": "s", "type": "slider"}))
    assert any("requires both min and max" in e for e in errs)


def test_number_max_must_exceed_min() -> None:
    errs = errors_for(tmpl({"id": "n", "type": "number", "min": 5, "max": 5}))
    assert any("max must exceed min" in e for e in errs)


def test_step_larger_than_range_is_rejected() -> None:
    errs = errors_for(tmpl({"id": "n", "type": "number", "min": 0, "max": 1, "step": 5}))
    assert any("step is larger than its range" in e for e in errs)


def test_bounds_on_a_non_numeric_type_are_rejected() -> None:
    errs = errors_for(tmpl({"id": "t", "type": "tags", "min": 1}))
    assert any("must not declare min" in e for e in errs)


def test_scale_on_a_non_scale_type_is_rejected() -> None:
    errs = errors_for(tmpl({"id": "n", "type": "number", "scale": {"min": 1, "max": 5}}))
    assert any("must not declare a scale" in e for e in errs)


def test_select_supports_allow_other_but_tags_does_not() -> None:
    validate_template(
        tmpl({"id": "s", "type": "select", "options": ["a", "b"], "allow_other": True})
    )
    errs = errors_for(tmpl({"id": "t", "type": "tags", "allow_other": True}))
    assert any("does not support allow_other" in e for e in errs)


# --- hotkeys (§2.4) ---------------------------------------------------------


def test_rating_gets_digit_keys_like_a_likert() -> None:
    a = assign_hotkeys([{"id": "r", "type": "rating", "scale": {"min": 1, "max": 5}}])
    assert a.errors == []
    assert sorted(a.key_map("r").values()) == ["1", "2", "3", "4", "5"]


def test_boolean_gets_two_keys_from_its_implicit_labels() -> None:
    a = assign_hotkeys([{"id": "b", "type": "boolean"}])
    assert a.errors == []
    assert a.key_map("b") == {"Yes": "1", "No": "2"}


def test_dropdowns_and_typing_inputs_claim_no_keys() -> None:
    """select/multiselect/ranking exist *because* the option list is long — giving
    each option a key would exhaust the budget and collide with everything else."""
    a = assign_hotkeys(
        [
            {"id": "s", "type": "select", "options": ["a", "b", "c"]},
            {"id": "rk", "type": "ranking", "options": ["a", "b"]},
            {"id": "n", "type": "number", "min": 0, "max": 5},
            {"id": "radio", "type": "radio", "options": ["x", "y"]},
        ]
    )
    assert a.errors == []
    assert a.key_map("s") == {} and a.key_map("rk") == {} and a.key_map("n") == {}
    # …and the radio still gets the digits, unpolluted.
    assert a.key_map("radio") == {"x": "1", "y": "2"}


def test_hotkey_conflicts_still_fail_validation_with_new_types() -> None:
    errs = errors_for(
        tmpl(
            {"id": "b", "type": "boolean"},
            {
                "id": "r",
                "type": "rating",
                "scale": {"min": 1, "max": 3},
                "hotkeys": ["1", "x", "y"],
            },
        )
    )
    assert any("duplicate hotkey '1'" in e for e in errs)


# --- canonicalization (§2.3, §2.6 step 3) -----------------------------------

SCHEMA = tmpl(*VALID_BY_TYPE.values())


def canon(raw):
    return canonicalize(SCHEMA, raw, None)


def test_boolean_canonicalizes_string_tokens() -> None:
    assert canon({"b": "yes"})["b"] is True
    assert canon({"b": "false"})["b"] is False
    assert canon({"b": True})["b"] is True


def test_number_and_slider_coerce_numeric_strings() -> None:
    assert canon({"n": "7"})["n"] == 7
    assert canon({"sl": "0.25"})["sl"] == 0.25
    assert canon({"n": "not a number"})["n"] == "not a number"  # pass through, gold won't match


def test_rating_is_an_integer() -> None:
    assert canon({"r": "4"})["r"] == 4
    assert canon({"r": 4.0})["r"] == 4


def test_tags_are_trimmed_lowercased_and_deduplicated() -> None:
    assert canon({"t": ["  Spam ", "spam", "Phishing"]})["t"] == ["spam", "phishing"]


def test_tags_accept_a_comma_separated_string() -> None:
    assert canon({"t": "a, B ,a"})["t"] == ["a", "b"]


def test_ranking_preserves_order() -> None:
    assert canon({"rk": ["c", "a", "b"]})["rk"] == ["c", "a", "b"]


def test_date_passes_through_untouched() -> None:
    assert canon({"d": "2026-07-26"})["d"] == "2026-07-26"


# --- matching (§6.4) --------------------------------------------------------


def test_ranking_defaults_to_ordered_matching() -> None:
    """[A,B] and [B,A] are the same *set* but opposite rankings — the default
    ``exact`` set comparison would call them equal, so ranking defaults to
    ``ordered``."""
    rule = rule_for(None, "rk", "ranking")
    assert rule.match == "ordered"
    assert not values_match(["a", "b"], ["b", "a"], rule)
    assert values_match(["a", "b"], ["a", "b"], rule)


def test_a_checkbox_key_still_compares_as_a_set() -> None:
    rule = rule_for(None, "flags", "checkbox")
    assert values_match(["a", "b"], ["b", "a"], rule)


def test_an_explicit_policy_beats_the_per_type_default() -> None:
    rule = rule_for({"rk": {"match": "jaccard", "threshold": 0.5}}, "rk", "ranking")
    assert rule.match == "jaccard"
    assert values_match(["a", "b"], ["b", "a"], rule)


def test_within_still_applies_to_a_slider() -> None:
    rule = MatchRule(match="within", tolerance=0.1)
    assert values_match(0.45, 0.5, rule)
    assert not values_match(0.2, 0.5, rule)


# --- versioning (§2.5, §12 invariant 3) -------------------------------------


def test_widening_a_slider_range_bumps_the_version() -> None:
    old = tmpl({"id": "s", "type": "slider", "min": 0, "max": 1})
    new = tmpl({"id": "s", "type": "slider", "min": 0, "max": 100})
    assert is_schema_affecting(old, new)


def test_relabeling_a_number_field_does_not_bump_the_version() -> None:
    old = tmpl({"id": "n", "type": "number", "min": 0, "max": 10, "label": "Count"})
    new = tmpl({"id": "n", "type": "number", "min": 0, "max": 10, "label": "How many?"})
    assert not is_schema_affecting(old, new)

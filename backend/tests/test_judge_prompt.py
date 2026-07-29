"""Prompt assembly + reply parsing (M7, §7.1). No database needed.

The tests that matter here are the blinding ones. A judge prompt that names
items "A" and "B" would answer in canonical space, and every order-bias number in
§9 would read a perfect 0.5 — not because the judge is unbiased, but because we
never gave it a chance to be biased. So the suite asserts the *position* wording,
the variant-driven ordering, and the absence of any A/B or gold vocabulary.
"""

import json

import pytest

from app.services.judges.parsing import ParseError, parse_response
from app.services.judges.prompt import (
    assemble_prompt,
    serialize_display,
    serialize_inputs,
    variant_key,
)
from app.services.templates.seed import IMAGE_CLASSIFICATION, SIDE_BY_SIDE, TEXT_SENTIMENT

PAIR_PAYLOAD = {
    "prompt": "Explain gravity to a child.",
    "response_a": "AAA Gravity pulls things down.",
    "response_b": "BBB Everything with mass attracts everything else.",
}


# --- display serialization + blinding ---------------------------------------


def test_panels_are_ordered_by_variant_and_named_by_position():
    """ "BA" shows item B on the left — the same thing the human sees (§2.7)."""
    ab = serialize_display(SIDE_BY_SIDE, PAIR_PAYLOAD, "AB")
    ba = serialize_display(SIDE_BY_SIDE, PAIR_PAYLOAD, "BA")

    left_ab = next(s for s in ab if s.startswith("### Left"))
    left_ba = next(s for s in ba if s.startswith("### Left"))
    assert "AAA" in left_ab and "BBB" not in left_ab
    assert "BBB" in left_ba and "AAA" not in left_ba
    # Same content, opposite order — the only difference is presentation.
    assert sorted(s.split("\n", 1)[1] for s in ab) == sorted(s.split("\n", 1)[1] for s in ba)


def test_prompt_never_leaks_ab_identity_or_gold_status():
    prompt = assemble_prompt(
        SIDE_BY_SIDE,
        PAIR_PAYLOAD,
        guidelines_md="Prefer the clearer answer.",
        variant={"panel_order": "BA"},
    )
    text = prompt.user.lower()
    for leak in ("response_a", "response_b", "panel_order", "variant", "gold", "is_gold"):
        assert leak not in text, f"prompt leaked {leak!r}"
    assert "left" in text and "right" in text


def test_guidelines_and_answer_format_are_present():
    prompt = assemble_prompt(
        IMAGE_CLASSIFICATION,
        {"image_url": "http://x/1.png"},
        guidelines_md="Label what is actually visible.",
    )
    assert "Label what is actually visible." in prompt.user
    assert '"confidence"' in prompt.user
    assert '"reasoning"' in prompt.user
    assert prompt.field_ids == ["category"]


def test_optional_missing_display_block_is_skipped_not_rendered_as_none():
    """An absent optional block must not become the literal text "None"."""
    sections = serialize_display(IMAGE_CLASSIFICATION, {"image_url": "http://x/1.png"}, None)
    assert not any("None" in s for s in sections)
    assert len(sections) == 1


# --- input serialization -----------------------------------------------------


def test_inputs_render_options_allow_other_and_shapes():
    lines, ids = serialize_inputs(IMAGE_CLASSIFICATION)
    assert ids == ["category"]
    body = "\n".join(lines)
    assert '- "category" (radio)' in body
    assert '["cat", "dog", "bird"]' in body
    assert "other:" in body
    assert "value shape: string" in body


def test_likert_scale_is_rendered_as_its_numeric_range():
    lines, ids = serialize_inputs(TEXT_SENTIMENT)
    assert "confidence" in ids
    body = "\n".join(lines)
    assert '- "confidence" (likert)' in body
    assert "one of:" in body


def test_prompt_template_placeholders_are_honored():
    prompt = assemble_prompt(
        IMAGE_CLASSIFICATION,
        {"image_url": "http://x/1.png"},
        guidelines_md="G",
        prompt_template="PREAMBLE\n\n{guidelines}\n\n{task}",
    )
    assert prompt.user.startswith("PREAMBLE")
    assert prompt.user.index("PREAMBLE") < prompt.user.index("## Questions")


def test_prompt_template_without_placeholders_still_gets_the_task():
    """A preamble that forgets {task} must not silently produce a task-free prompt."""
    prompt = assemble_prompt(
        IMAGE_CLASSIFICATION, {"image_url": "http://x/1.png"}, prompt_template="Be strict."
    )
    assert "Be strict." in prompt.user
    assert "## Questions" in prompt.user


def test_digest_is_stable_and_variant_sensitive():
    a = assemble_prompt(SIDE_BY_SIDE, PAIR_PAYLOAD, variant={"panel_order": "AB"})
    a2 = assemble_prompt(SIDE_BY_SIDE, PAIR_PAYLOAD, variant={"panel_order": "AB"})
    b = assemble_prompt(SIDE_BY_SIDE, PAIR_PAYLOAD, variant={"panel_order": "BA"})
    assert a.digest() == a2.digest()
    assert a.digest() != b.digest()


def test_variant_key_is_the_variant_string_or_empty():
    assert variant_key(SIDE_BY_SIDE, {"panel_order": "BA"}) == "BA"
    assert variant_key(IMAGE_CLASSIFICATION, None) == ""


# --- reply parsing -----------------------------------------------------------


def test_parses_plain_json_fenced_json_and_chatty_json():
    body = {"answers": {"category": "cat"}, "confidence": 0.9, "reasoning": "It is a cat."}
    for text in (
        json.dumps(body),
        f"```json\n{json.dumps(body)}\n```",
        f"Sure! Here is my answer:\n\n{json.dumps(body)}\n\nHope that helps.",
    ):
        parsed = parse_response(text, ["category"])
        assert parsed.raw == {"category": "cat"}
        assert parsed.confidence == 0.9
        assert parsed.reasoning == "It is a cat."


def test_parses_a_bare_answer_object_without_the_envelope():
    parsed = parse_response('{"category": "dog"}', ["category"])
    assert parsed.raw == {"category": "dog"}
    assert parsed.confidence is None


def test_confidence_accepts_percentages_and_clamps():
    assert parse_response('{"answers":{"a":1},"confidence":85}', ["a"]).confidence == 0.85
    assert parse_response('{"answers":{"a":1},"confidence":"90%"}', ["a"]).confidence == 0.9
    assert parse_response('{"answers":{"a":1},"confidence":-3}', ["a"]).confidence == 0.0
    assert parse_response('{"answers":{"a":1},"confidence":"nope"}', ["a"]).confidence is None


def test_unknown_fields_are_dropped_and_reported():
    parsed = parse_response('{"answers": {"category": "cat", "vibes": "good"}}', ["category"])
    assert parsed.raw == {"category": "cat"}
    assert parsed.unknown_fields == ["vibes"]


def test_missing_required_fields_are_reported_not_invented():
    parsed = parse_response(
        '{"answers": {"sentiment": "positive"}}',
        ["sentiment", "confidence"],
        required_ids=["sentiment", "confidence"],
    )
    assert parsed.missing_fields == ["confidence"]
    assert "confidence" not in parsed.raw


@pytest.mark.parametrize(
    "text",
    ["", "   ", "I refuse to answer.", "{not json at all", '{"answers": {}}'],
)
def test_unreadable_replies_raise_rather_than_guess(text):
    with pytest.raises(ParseError):
        parse_response(text, ["category"])


def test_a_reply_answering_only_unknown_fields_raises():
    with pytest.raises(ParseError):
        parse_response('{"answers": {"nonsense": 1}}', ["category"])

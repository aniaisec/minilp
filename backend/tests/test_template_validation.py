"""Template validation, hotkeys, versioning, preview (§2.1-§2.5). Pure — no DB."""

import copy

import pytest

from app.services.templates import (
    TemplateValidationError,
    assign_hotkeys,
    is_schema_affecting,
    render_preview,
    validate_template,
)
from app.services.templates.seed import GALLERY


def _minimal() -> dict:
    return {
        "name": "t",
        "inputs": [
            {
                "id": "cat",
                "type": "radio",
                "label": "Pick",
                "options": ["a", "b", "c"],
                "required": True,
            }
        ],
    }


# --- structural / semantic validation ---


def test_minimal_template_valid() -> None:
    validate_template(_minimal())


def test_unknown_input_type_rejected() -> None:
    t = _minimal()
    t["inputs"][0]["type"] = "slider"
    with pytest.raises(TemplateValidationError):
        validate_template(t)


def test_duplicate_input_id_rejected() -> None:
    t = _minimal()
    t["inputs"].append(dict(t["inputs"][0]))
    with pytest.raises(TemplateValidationError) as ei:
        validate_template(t)
    assert any("duplicate input id" in e for e in ei.value.errors)


def test_radio_needs_two_options() -> None:
    t = _minimal()
    t["inputs"][0]["options"] = ["only"]
    with pytest.raises(TemplateValidationError):
        validate_template(t)


def test_bad_source_ref_rejected() -> None:
    t = _minimal()
    t["display"] = [{"type": "text", "source": "unit.text"}]
    with pytest.raises(TemplateValidationError) as ei:
        validate_template(t)
    assert any("$unit" in e for e in ei.value.errors)


def test_invalid_render_option_rejected() -> None:
    t = _minimal()
    t["display"] = [{"type": "image", "source": "$unit.img", "render": {"collapsible": True}}]
    with pytest.raises(TemplateValidationError) as ei:
        validate_template(t)
    assert any("render option" in e for e in ei.value.errors)


def test_allow_other_only_on_radio_checkbox() -> None:
    t = _minimal()
    t["inputs"][0] = {
        "id": "s",
        "type": "free_text",
        "label": "x",
        "allow_other": True,
    }
    with pytest.raises(TemplateValidationError):
        validate_template(t)


# --- hotkeys (§2.4) ---


def test_duplicate_explicit_hotkeys_fail_save() -> None:
    t = _minimal()
    t["inputs"][0]["hotkeys"] = "auto"
    t["inputs"].append(
        {
            "id": "flags",
            "type": "checkbox",
            "label": "f",
            "options": ["x", "y"],
            "hotkeys": ["a", "a"],  # duplicate
        }
    )
    with pytest.raises(TemplateValidationError) as ei:
        validate_template(t)
    assert any("duplicate hotkey" in e for e in ei.value.errors)


def test_reserved_hotkey_fails_save() -> None:
    t = _minimal()
    t["inputs"][0]["hotkeys"] = ["a", "s", "c"]  # 's' is reserved (skip)
    with pytest.raises(TemplateValidationError) as ei:
        validate_template(t)
    assert any("reserved" in e for e in ei.value.errors)


def test_auto_hotkeys_first_input_digits_second_letters() -> None:
    t = _minimal()
    t["inputs"].append({"id": "q", "type": "checkbox", "label": "q", "options": ["p", "r"]})
    a = assign_hotkeys(t["inputs"])
    assert a.errors == []
    assert a.by_input["cat"]["options"] == {"a": "1", "b": "2", "c": "3"}
    # second choice input gets letters, skipping reserved d/g/s/u/o
    second = a.by_input["q"]["options"]
    assert list(second.values()) == ["a", "b"]


def test_allow_other_gets_o() -> None:
    t = _minimal()
    t["inputs"][0]["allow_other"] = True
    a = assign_hotkeys(t["inputs"])
    assert a.by_input["cat"]["other"] == "o"


def test_arrow_keys_only_for_choice_buttons() -> None:
    t = _minimal()
    t["inputs"][0]["hotkeys"] = ["←", "↓", "→"]  # radio, not choice_buttons
    with pytest.raises(TemplateValidationError) as ei:
        validate_template(t)
    assert any("arrow keys" in e for e in ei.value.errors)


# --- versioning (§2.5) ---


def test_layout_edit_is_presentation_only() -> None:
    old = _minimal()
    new = copy.deepcopy(old)
    new["layout"] = {"arrangement": "split", "ratio": [1, 1]}
    assert is_schema_affecting(old, new) is False


def test_hotkey_edit_is_presentation_only() -> None:
    old = _minimal()
    new = copy.deepcopy(old)
    new["inputs"][0]["hotkeys"] = ["x", "y", "z"]
    assert is_schema_affecting(old, new) is False


def test_options_change_is_schema_affecting() -> None:
    old = _minimal()
    new = copy.deepcopy(old)
    new["inputs"][0]["options"] = ["a", "b", "c", "d"]
    assert is_schema_affecting(old, new) is True


def test_adding_input_is_schema_affecting() -> None:
    old = _minimal()
    new = copy.deepcopy(old)
    new["inputs"].append({"id": "extra", "type": "free_text", "label": "x"})
    assert is_schema_affecting(old, new) is True


def test_retype_input_is_schema_affecting() -> None:
    old = _minimal()
    new = copy.deepcopy(old)
    new["inputs"][0]["type"] = "checkbox"
    assert is_schema_affecting(old, new) is True


# --- gallery round-trips (M1 acceptance) ---


@pytest.mark.parametrize("schema", GALLERY, ids=[t["name"] for t in GALLERY])
def test_gallery_validates_and_previews(schema: dict) -> None:
    validate_template(schema)
    preview = render_preview(schema, {})
    assert "inputs" in preview and "display" in preview
    # every input has its hotkey map present in the preview
    for inp in preview["inputs"]:
        assert "hotkeys" in inp


def test_side_by_side_preview_resolves_payload() -> None:
    sbs = next(t for t in GALLERY if t["name"] == "side-by-side-preference")
    payload = {"prompt": "Q?", "response_a": "A", "response_b": "B"}
    preview = render_preview(sbs, payload)
    assert preview["payload_valid"] is True
    # choice_buttons keeps its explicit arrow keys
    choice = next(i for i in preview["inputs"] if i["id"] == "choice")
    assert set(choice["hotkeys"].values()) == {"left", "down", "right"}

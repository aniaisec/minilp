# Extending MiniLP — adding a display block or input field

> The extensibility contract of [PLAN.md §2.6](../PLAN.md). Adding a new type touches
> **four places** and nothing else. Assignment, leasing, golds, agreement, reputation,
> merge and export never learn about your type, because they operate on JSON payloads
> and JSON answers — not on widgets.

If you find yourself editing a fifth place, something is wrong with the design of the
type, not with this document. Come back and say so.

---

## The contract

| # | Place | File | What you add |
|---|---|---|---|
| 1 | **Schema fragment** | `backend/app/services/templates/spec.py` (+ rules in `validation.py`) | the type name, its config keys, its declared value shape |
| 2 | **React widget** | `frontend/src/widgets/inputs/…` or `…/display/…`, registered in `frontend/src/widgets/registry.ts` | how it draws and how it collects |
| 3 | **Canonicalizer** *(optional)* | `backend/app/services/quality/canonical.py` (+ its mirror `frontend/src/render/canonical.ts`) | raw answer → canonical value |
| 4 | **Prompt serializer** *(optional)* | judge prompt assembly (M7) | how a model sees it |

Steps 3 and 4 are optional because sensible defaults exist: an answer with no
canonicalizer is stored as entered, and a type with no serializer is rendered
naively into the judge prompt. Write them when the default is *lossy*.

---

## Worked example: adding a `slider`

This is the real M6 change, start to finish.

### 1. Declare it in the schema

`backend/app/services/templates/spec.py`:

```python
M6_INPUT_TYPES = (..., "slider", ...)          # the type exists

VALUE_SHAPES = {
    ...,
    "slider": "number",                        # what a label stores (§2.3)
}

RANGE_INPUT_TYPES = ("number", "slider")       # uses min / max / step
BOUNDS_REQUIRED_TYPES = ("slider",)            # bounds are not optional for it
```

If the type carries new config keys, add them to `TEMPLATE_JSON_SCHEMA` in the same
file — that is the *structural* gate (types, enums, required keys).

Then the *semantic* rules JSON Schema can't express, in `validation.py`:

```python
if itype in BOUNDS_REQUIRED_TYPES and (lo is None or hi is None):
    errors.append(f"input '{iid}' ({itype}) requires both min and max")
if lo is not None and hi is not None and hi <= lo:
    errors.append(f"input '{iid}' ({itype}) max must exceed min")
```

Write the message for the person who will read it in the builder's error list, not
for yourself. `"input 'confidence' (slider) requires both min and max"` beats
`"invalid slider"`.

**Two things to decide here:**

- **Does it get hotkeys?** Add it to `CHOICE_INPUT_TYPES` only if it presents a
  *small, fixed* set of options. `rating` and `boolean` are in; `select` and
  `ranking` deliberately are not — they exist for long lists, and per-option keys
  would exhaust the 1–9 + letters budget and collide with everything else on the
  page (§2.4). If the type has options that aren't `options` (like `boolean`'s
  implicit Yes/No), teach `_option_labels` in `hotkeys.py` about it.
- **Does the edit bump the version?** `versioning.py` decides. Anything that
  changes the *domain of the stored value* belongs in `_input_signature` — that
  is why `min`/`max`/`step` are in there: widening a slider from 0–10 to 0–100
  re-shapes what a stored `7` means, exactly like adding a likert point does
  (§2.5, §12 invariant 3).

### 2. Write the widget

`frontend/src/widgets/inputs/SliderInput.tsx`. Widgets are **controlled**: they
render the current raw value and report changes; the annotation view owns the
answer map and the keyboard dispatcher, so mouse and keyboard can never diverge.

```tsx
export function SliderInput({ input, value, onChange }: InputWidgetProps) {
  const min = input.min ?? 0;
  const max = input.max ?? 1;
  return (
    <div className="mlp-field" data-testid={`input-${input.id}`}>
      <input type="range" min={min} max={max} step={input.step}
             value={typeof value === "number" ? value : min}
             data-testid={`${input.id}-slider`}
             onChange={(e) => onChange(Number(e.target.value))} />
    </div>
  );
}
```

Register it:

```ts
// frontend/src/widgets/registry.ts
export const INPUT_WIDGETS = { ..., slider: SliderInput };
```

Registering is also what puts the type in the visual builder's palette — the
palette is derived from the registry, so a type the renderer can't draw can never
be dropped onto a canvas.

**Also update, if your type needs it:**

- `frontend/src/render/complete.ts` — when is this field *answered*? The default
  ("not null") is wrong for anything array-shaped, and wrong for `boolean` where
  `false` is a real answer.
- `frontend/src/render/options.ts` — `resolveOptions` if the option list maps to
  something other than its own label (likert/rating → integers, boolean → true/false).
- `frontend/src/views/admin/builder/schema.ts` — `newInput`'s defaults, so a
  freshly dropped field is *immediately valid*. A palette entry that lands broken
  is a palette entry nobody uses.

### 3. Canonicalize (if the raw answer isn't already the value)

`backend/app/services/quality/canonical.py`. The backend is authoritative — the
client's `value` is advisory (§2.6), so a wrong or malicious client cannot corrupt
gold grading, agreement or merge.

```python
_BY_TYPE = {
    ...,
    "slider": _to_number,
}
```

Be **forgiving about input, strict about output**: an HTML number field yields a
string, a checkbox yields `"true"`. Convert what you recognize and *pass through*
what you don't — an unparseable answer stored as-is simply fails to match a gold,
which is the correct outcome. Silently coercing it to `0` is not.

Mirror the function in `frontend/src/render/canonical.ts`. The two are kept in
sync by shared fixtures: a type that canonicalizes differently on the two sides
shows up as a gold/agreement discrepancy in tests.

**Does your value shape need a different notion of equality?** Add it to
`DEFAULT_MATCH_BY_INPUT_TYPE` in `services/quality/matching.py`. `ranking` is the
example: it stores an ordered array, so the set-comparison `exact` uses for
checkbox answers would call `[A,B]` and `[B,A]` identical — the opposite of what a
ranking means. It defaults to `ordered` instead. An explicit project policy still
wins over the default.

### 4. Serialize for judges (M7)

A judge sees the template as text. The default renders label + options, which is
right for most types. Override when the naive rendering is lossy — an `image_region`
answer serialized as raw coordinates tells a model nothing useful.

---

## Adding a *display* block

Same shape, fewer moving parts — display blocks have no value, so steps 3 and 4
mostly don't apply:

1. `DISPLAY_TYPES` and `RENDER_OPTIONS` in `spec.py` — the render options are
   validated per type, so an option that isn't in the table is a save-time error
   rather than a silently-ignored key.
2. A component in `frontend/src/widgets/display/`, registered in `DISPLAY_WIDGETS`.
   Mirror the allowed render options in `Inspector.tsx`'s `RENDER_OPTIONS` so the
   builder offers exactly what validation accepts.
3. `sample.py`'s `_EXAMPLES` — what a generated example payload should contain for
   this block type, so the gallery preview and the wizard prefill work on day one.

Remember that layout and render options are **presentation-only** (§2.2): they must
never affect a stored value, which is what lets a template be restyled mid-project
without invalidating collected labels.

---

## Tests to write

Follow the M6 palette suite — `backend/tests/test_palette_m6.py` and
`frontend/src/widgets/palette.test.tsx` — which cover, for every type:

- **it validates on its own**, and one of everything validates together;
- **each rejection rule fires** with a readable message;
- **hotkeys**: gets them or deliberately doesn't, and never conflicts;
- **the value shape**: what the widget reports for a click, and what the
  canonicalizer stores for a hostile input;
- **completeness**: what counts as answered (`false` and `0` do);
- **versioning**: which edits bump and which don't.

And the one that matters most: `frontend/src/views/admin/builder/schema.test.ts`
asserts *every palette entry produces a valid field on its own*. Add your type to
the palette and that test covers it automatically — if `newInput` returns something
that doesn't validate, the suite says so before a user ever drags it.

---

## Why it's this small

Everything downstream of a label reads `label.value` — a JSON object keyed by input
id. Golds match per key (§6.1), agreement is computed per key (§6.3), consensus
groups per key (§6.4), export emits per key (§10). None of them ask what widget
produced the key. That is the whole trick: **the value shape is the interface**, and
a new type is a new shape plus a way to draw it.

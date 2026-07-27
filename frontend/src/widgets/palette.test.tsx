// M6 expanded field palette (§2.1, §2.3, §2.6) — every new widget renders,
// collects the declared value shape, and stays keyboard-reachable.

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { InputField } from "../api/types";
import { assignHotkeys } from "../hotkeys/assign";
import { canonicalize } from "../render/canonical";
import { inputAnswered } from "../render/complete";
import { INPUT_WIDGETS, SUPPORTED_INPUT_TYPES } from "./registry";

const M6_TYPES = [
  "number",
  "select",
  "multiselect",
  "boolean",
  "rating",
  "slider",
  "tags",
  "ranking",
  "date",
  "datetime",
] as const;

const FIELDS: Record<string, InputField> = {
  number: { id: "n", type: "number", label: "Count", min: 0, max: 10, step: 1 },
  select: { id: "s", type: "select", label: "Category", options: ["cat", "dog", "bird"] },
  multiselect: { id: "m", type: "multiselect", label: "Flags", options: ["blurry", "dark"] },
  boolean: { id: "b", type: "boolean", label: "Escalate?" },
  rating: { id: "r", type: "rating", label: "Quality", scale: { min: 1, max: 5 } },
  slider: { id: "sl", type: "slider", label: "Confidence", min: 0, max: 1, step: 0.1 },
  tags: { id: "t", type: "tags", label: "Topics" },
  ranking: { id: "rk", type: "ranking", label: "Rank", options: ["a", "b", "c"] },
  date: { id: "d", type: "date", label: "Seen on" },
  datetime: { id: "dt", type: "datetime", label: "Seen at" },
};

function renderInput(field: InputField, value?: unknown) {
  const onChange = vi.fn();
  const Widget = INPUT_WIDGETS[field.type]!;
  const hotkeys = assignHotkeys([field]).byInput[field.id];
  render(<Widget input={field} hotkeys={hotkeys} value={value} onChange={onChange} />);
  return { onChange };
}

// --- registry ---------------------------------------------------------------

describe("registry (§2.6)", () => {
  it("has a widget for every M6 palette type", () => {
    for (const type of M6_TYPES) {
      expect(INPUT_WIDGETS[type], `${type} has no widget`).toBeTruthy();
      expect(SUPPORTED_INPUT_TYPES).toContain(type);
    }
  });
});

// --- rendering --------------------------------------------------------------

describe("each new widget renders with its label", () => {
  it.each(M6_TYPES)("%s", (type) => {
    renderInput(FIELDS[type]);
    expect(screen.getByTestId(`input-${FIELDS[type].id}`)).toBeInTheDocument();
    expect(screen.getByText(FIELDS[type].label!)).toBeInTheDocument();
  });
});

// --- collecting the declared value shape ------------------------------------

describe("value shapes (§2.3)", () => {
  it("number reports a number, not a string", async () => {
    const { onChange } = renderInput(FIELDS.number);
    await userEvent.type(screen.getByTestId("n-number"), "7");
    expect(onChange).toHaveBeenLastCalledWith(7);
  });

  it("select reports the chosen option string", async () => {
    const { onChange } = renderInput(FIELDS.select);
    await userEvent.selectOptions(screen.getByTestId("s-select"), "dog");
    expect(onChange).toHaveBeenLastCalledWith("dog");
  });

  it("multiselect toggles membership in an array", async () => {
    const { onChange } = renderInput(FIELDS.multiselect, ["blurry"]);
    await userEvent.click(screen.getByTestId("m-opt-dark"));
    expect(onChange).toHaveBeenLastCalledWith(["blurry", "dark"]);
  });

  it("multiselect deselects an already-chosen option", async () => {
    const { onChange } = renderInput(FIELDS.multiselect, ["blurry"]);
    await userEvent.click(screen.getByTestId("m-opt-blurry"));
    expect(onChange).toHaveBeenLastCalledWith([]);
  });

  it("boolean reports true / false, not 'Yes' / 'No'", async () => {
    const { onChange } = renderInput(FIELDS.boolean);
    await userEvent.click(screen.getByTestId("b-opt-Yes"));
    expect(onChange).toHaveBeenLastCalledWith(true);
    await userEvent.click(screen.getByTestId("b-opt-No"));
    expect(onChange).toHaveBeenLastCalledWith(false);
  });

  it("rating reports an integer and fills the stars up to it", async () => {
    const { onChange } = renderInput(FIELDS.rating, 3);
    expect(screen.getByTestId("r-readout")).toHaveTextContent("3 / 5");
    await userEvent.click(screen.getByTestId("r-opt-4"));
    expect(onChange).toHaveBeenLastCalledWith(4);
  });

  it("slider reports a number and shows the current value", () => {
    renderInput(FIELDS.slider, 0.7);
    expect(screen.getByTestId("sl-slider-value")).toHaveTextContent("0.7");
  });

  it("tags commits on Enter and builds an array", async () => {
    const { onChange } = renderInput(FIELDS.tags, []);
    await userEvent.type(screen.getByTestId("t-tag-entry"), "spam{Enter}");
    expect(onChange).toHaveBeenLastCalledWith(["spam"]);
  });

  it("tags removes a chip", async () => {
    const { onChange } = renderInput(FIELDS.tags, ["spam", "phishing"]);
    await userEvent.click(screen.getByTestId("t-remove-spam"));
    expect(onChange).toHaveBeenLastCalledWith(["phishing"]);
  });

  it("date reports an ISO string", async () => {
    const { onChange } = renderInput(FIELDS.date);
    await userEvent.type(screen.getByTestId("d-date"), "2026-07-26");
    expect(onChange).toHaveBeenLastCalledWith("2026-07-26");
  });
});

// --- ranking: order is the answer -------------------------------------------

describe("ranking (§2.3 ordered array)", () => {
  it("starts from the declared option order", () => {
    renderInput(FIELDS.ranking);
    const rows = screen.getAllByTestId(/^rk-rank-/);
    expect(rows.map((r) => r.textContent)).toEqual(
      expect.arrayContaining([expect.stringContaining("a")]),
    );
    expect(screen.getByTestId("rk-rank-a")).toHaveAttribute("data-position", "1");
    expect(screen.getByTestId("rk-rank-c")).toHaveAttribute("data-position", "3");
  });

  it("moves an item with the ↓ button", async () => {
    const { onChange } = renderInput(FIELDS.ranking, ["a", "b", "c"]);
    await userEvent.click(screen.getByTestId("rk-down-a"));
    expect(onChange).toHaveBeenLastCalledWith(["b", "a", "c"]);
  });

  it("moves an item with Alt+ArrowUp — a ranking must be keyboard-completable", async () => {
    const { onChange } = renderInput(FIELDS.ranking, ["a", "b", "c"]);
    const row = screen.getByTestId("rk-rank-c");
    row.focus();
    await userEvent.keyboard("{Alt>}{ArrowUp}{/Alt}");
    expect(onChange).toHaveBeenLastCalledWith(["a", "c", "b"]);
  });

  it("cannot move the first item up", async () => {
    const { onChange } = renderInput(FIELDS.ranking, ["a", "b", "c"]);
    expect(screen.getByTestId("rk-up-a")).toBeDisabled();
    expect(onChange).not.toHaveBeenCalled();
  });
});

// --- hotkeys (§2.4) ---------------------------------------------------------

describe("hotkeys", () => {
  it("rating and boolean get keys; dropdowns and typing inputs do not", () => {
    const a = assignHotkeys([FIELDS.rating]);
    expect(Object.values(a.byInput.r.options)).toEqual(["1", "2", "3", "4", "5"]);

    const b = assignHotkeys([FIELDS.boolean]);
    expect(b.byInput.b.options).toEqual({ Yes: "1", No: "2" });

    const c = assignHotkeys([FIELDS.select, FIELDS.ranking, FIELDS.number, FIELDS.tags]);
    expect(c.errors).toEqual([]);
    expect(c.byInput.s.options).toEqual({});
    expect(c.byInput.rk.options).toEqual({});
  });

  it("matches the backend assignment for a mixed template", () => {
    // First choice input takes the digits; the next takes letters (§2.4).
    const a = assignHotkeys([
      { id: "verdict", type: "radio", options: ["ok", "bad"] },
      { id: "escalate", type: "boolean" },
    ]);
    expect(a.errors).toEqual([]);
    expect(a.byInput.verdict.options).toEqual({ ok: "1", bad: "2" });
    expect(Object.values(a.byInput.escalate.options)).toEqual(["a", "b"]);
  });
});

// --- completeness (§2.3 required) -------------------------------------------

describe("required gating", () => {
  it("treats boolean false as answered", () => {
    expect(inputAnswered(FIELDS.boolean, false)).toBe(true);
    expect(inputAnswered(FIELDS.boolean, undefined)).toBe(false);
  });

  it("treats number 0 as answered", () => {
    expect(inputAnswered(FIELDS.number, 0)).toBe(true);
    expect(inputAnswered(FIELDS.number, "")).toBe(false);
  });

  it("requires at least one tag / ranking entry", () => {
    expect(inputAnswered(FIELDS.tags, [])).toBe(false);
    expect(inputAnswered(FIELDS.tags, ["spam"])).toBe(true);
    expect(inputAnswered(FIELDS.ranking, ["a", "b", "c"])).toBe(true);
  });

  it("rejects a whitespace-only date", () => {
    expect(inputAnswered(FIELDS.date, "  ")).toBe(false);
    expect(inputAnswered(FIELDS.date, "2026-07-26")).toBe(true);
  });
});

// --- canonicalization mirrors the backend (§2.6) ----------------------------

describe("canonicalization", () => {
  const schema = { name: "t", inputs: Object.values(FIELDS) };

  it("folds tags to trimmed, lower-case, de-duplicated entries", () => {
    expect(canonicalize(schema, { t: ["  Spam ", "spam", "Phishing"] }, null).t).toEqual([
      "spam",
      "phishing",
    ]);
  });

  it("coerces boolean tokens and numeric strings", () => {
    expect(canonicalize(schema, { b: "yes" }, null).b).toBe(true);
    expect(canonicalize(schema, { n: "7" }, null).n).toBe(7);
    expect(canonicalize(schema, { sl: "0.25" }, null).sl).toBe(0.25);
    expect(canonicalize(schema, { r: "4" }, null).r).toBe(4);
  });

  it("leaves a ranking's order alone", () => {
    expect(canonicalize(schema, { rk: ["c", "a", "b"] }, null).rk).toEqual(["c", "a", "b"]);
  });

  it("passes an unparseable number through so a gold simply fails to match", () => {
    expect(canonicalize(schema, { n: "twelve" }, null).n).toBe("twelve");
  });
});

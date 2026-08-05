// Annotation widget accessibility (§ UX plan, phase 4).
//
// palette.test.tsx proves each widget collects its declared value shape. This
// file proves the widgets *say* what they are doing — which is the half the
// phase-4 audit found missing, and the half no amount of clicking through the
// UI will catch.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { InputField } from "../api/types";
import { assignHotkeys } from "../hotkeys/assign";
import { INPUT_WIDGETS } from "./registry";

function renderInput(field: InputField, value?: unknown) {
  const onChange = vi.fn();
  const Widget = INPUT_WIDGETS[field.type]!;
  const hotkeys = assignHotkeys([field]).byInput[field.id];
  const view = render(
    <Widget input={field} hotkeys={hotkeys} value={value} onChange={onChange} />,
  );
  const rerender = (next: unknown) =>
    view.rerender(
      <Widget input={field} hotkeys={hotkeys} value={next} onChange={onChange} />,
    );
  return { onChange, rerender };
}

// --- ranking ----------------------------------------------------------------

const RANKING: InputField = {
  id: "rk",
  type: "ranking",
  label: "Rank the issues",
  options: ["blurry", "cropped", "dark"],
};

describe("ranking — a move has to be perceivable without watching it", () => {
  it("announces the item and its new position", async () => {
    const { onChange } = renderInput(RANKING);
    await userEvent.setup().click(screen.getByTestId("rk-down-blurry"));

    expect(onChange).toHaveBeenCalledWith(["cropped", "blurry", "dark"]);
    expect(screen.getByTestId("rk-rank-announcer")).toHaveTextContent(
      "blurry moved to position 2 of 3.",
    );
  });

  it("announces keyboard moves on the same path as button moves", async () => {
    renderInput(RANKING);
    const row = screen.getByTestId("rk-rank-dark");
    row.focus();
    await userEvent.setup().keyboard("{Alt>}{ArrowUp}{/Alt}");
    expect(screen.getByTestId("rk-rank-announcer")).toHaveTextContent(
      "dark moved to position 2 of 3.",
    );
  });

  it("says nothing when the move was refused at an end", async () => {
    const { onChange } = renderInput(RANKING);
    const row = screen.getByTestId("rk-rank-blurry");
    row.focus();
    await userEvent.setup().keyboard("{Alt>}{ArrowUp}{/Alt}");
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByTestId("rk-rank-announcer")).toHaveTextContent("");
  });

  it("gives each row its position in its own accessible name", () => {
    renderInput(RANKING);
    expect(screen.getByTestId("rk-rank-cropped")).toHaveAccessibleName(
      "cropped, position 2 of 3",
    );
  });

  it("attaches the keyboard instructions to the list rather than leaving them nearby", () => {
    renderInput(RANKING);
    const list = screen.getByTestId("rk-ranking");
    const described = document.getElementById(list.getAttribute("aria-describedby") ?? "");
    expect(described?.textContent).toMatch(/Alt/);
  });

  it("keeps a non-drag path: every row has enabled move buttons except at the ends", () => {
    // Drag-and-drop with no keyboard alternative is a WCAG 2.2 failure outright,
    // so this is a correctness test, not a nicety.
    renderInput(RANKING);
    expect(screen.getByTestId("rk-up-blurry")).toBeDisabled();
    expect(screen.getByTestId("rk-down-blurry")).toBeEnabled();
    expect(screen.getByTestId("rk-up-dark")).toBeEnabled();
    expect(screen.getByTestId("rk-down-dark")).toBeDisabled();
  });
});

// --- rating -----------------------------------------------------------------

describe("rating — a star has to mean something out loud", () => {
  it("names each star with its scale word and its position", () => {
    renderInput({
      id: "q",
      type: "rating",
      label: "Framing",
      scale: { points: 5, labels: ["unusable", "poor", "ok", "good", "excellent"] },
    });
    expect(screen.getByTestId("q-opt-4")).toHaveAccessibleName("good — 4 of 5");
  });

  it("falls back to the bare position when the scale has no words", () => {
    renderInput({ id: "q", type: "rating", label: "Framing", scale: { min: 1, max: 5 } });
    expect(screen.getByTestId("q-opt-4")).toHaveAccessibleName("4 of 5");
  });

  it("makes the readout a polite live region so a change is heard", () => {
    const { rerender } = renderInput({
      id: "q",
      type: "rating",
      label: "Framing",
      scale: { min: 1, max: 5 },
    });
    const readout = screen.getByTestId("q-readout");
    expect(readout).toHaveAttribute("aria-live", "polite");
    expect(readout).toHaveTextContent("not rated");

    rerender(3);
    expect(screen.getByTestId("q-readout")).toHaveTextContent("3 / 5");
  });
});

// --- free text --------------------------------------------------------------

describe("free text — validation has to be attached, not adjacent", () => {
  it("associates help text with the field", () => {
    renderInput({ id: "notes", type: "free_text", label: "Notes", help: "Optional." });
    expect(screen.getByTestId("notes-text")).toHaveAccessibleDescription("Optional.");
  });

  it("stays quiet until the field has been left", async () => {
    renderInput({ id: "notes", type: "free_text", label: "Notes", required: true });
    const box = screen.getByTestId("notes-text");
    expect(box).not.toHaveAttribute("aria-invalid");
    expect(screen.queryByTestId("notes-error")).toBeNull();

    // Telling someone a field is required before they have had a chance to fill
    // it in is scolding, not helping.
    await userEvent.setup().click(box);
    await userEvent.setup().tab();
    expect(box).toHaveAttribute("aria-invalid", "true");
    expect(box).toHaveAccessibleDescription("This answer is required.");
  });
});

// --- number -----------------------------------------------------------------

describe("number — the bounds have to be readable and enforceable", () => {
  const FIELD: InputField = { id: "n", type: "number", label: "Count", min: 0, max: 10 };

  it("describes the accepted range", () => {
    renderInput(FIELD, 5);
    expect(screen.getByTestId("n-number")).toHaveAccessibleDescription("0 … 10");
  });

  it("marks an out-of-range value invalid and says what would be valid", () => {
    renderInput(FIELD, 14);
    const box = screen.getByTestId("n-number");
    expect(box).toHaveAttribute("aria-invalid", "true");
    expect(box.getAttribute("aria-describedby")).toContain(
      screen.getByTestId("n-error").id,
    );
    expect(screen.getByTestId("n-error")).toHaveTextContent(
      "Enter a value between 0 and 10.",
    );
  });

  it("says nothing about an empty field, which is not the same as a wrong one", () => {
    renderInput(FIELD);
    expect(screen.getByTestId("n-number")).not.toHaveAttribute("aria-invalid");
    expect(screen.queryByTestId("n-error")).toBeNull();
  });
});

// The visual builder as a user drives it (§2.5, §11, M6 acceptance).
//
// The claims under test are the ones the milestone makes: you can build a working
// template from scratch by dropping fields onto a canvas, reorder them (with a
// mouse *or* a keyboard), edit each field inline, and switch to the JSON view
// without losing anything — because the two are views of one document.

import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { TemplateSchema } from "../../../api/types";
import { PALETTE_MIME } from "./Canvas";
import { TemplateBuilder } from "./TemplateBuilder";
import { blankTemplate } from "./schema";

/** Host that owns the schema, like the real entry points do. */
function Host({
  initial,
  onSave,
  onSchema,
}: {
  initial?: TemplateSchema;
  onSave?: () => void;
  onSchema?: (s: TemplateSchema) => void;
}) {
  const [schema, setSchema] = useState<TemplateSchema>(initial ?? blankTemplate());
  return (
    <TemplateBuilder
      schema={schema}
      onChange={(next) => {
        setSchema(next);
        onSchema?.(next);
      }}
      onSave={onSave}
      showPreview={false}
    />
  );
}

function inputRows() {
  return screen.getByTestId("canvas-inputs").querySelectorAll(".mlp-canvas-item");
}

function inputTitles(): string[] {
  return Array.from(inputRows()).map(
    (row) => row.querySelector(".mlp-canvas-title")?.textContent ?? "",
  );
}

// --- building from scratch --------------------------------------------------

describe("building a template from scratch", () => {
  it("starts from a valid blank template", () => {
    render(<Host onSave={vi.fn()} />);
    expect(screen.queryByTestId("builder-errors")).not.toBeInTheDocument();
    expect(screen.getByTestId("builder-save")).toBeEnabled();
  });

  it("adds a field by clicking a palette entry", async () => {
    render(<Host />);
    expect(inputRows()).toHaveLength(1);
    await userEvent.click(screen.getByTestId("palette-rating"));
    expect(inputRows()).toHaveLength(2);
    expect(inputTitles()[1]).toContain("Rating");
  });

  it("adds a field by dropping a palette entry on the canvas", () => {
    render(<Host />);
    const data = new Map<string, string>();
    const dataTransfer = {
      setData: (k: string, v: string) => data.set(k, v),
      getData: (k: string) => data.get(k) ?? "",
      effectAllowed: "copy",
    };
    fireEvent.dragStart(screen.getByTestId("palette-slider"), { dataTransfer });
    fireEvent.drop(screen.getByTestId("canvas-inputs"), { dataTransfer });
    expect(inputRows()).toHaveLength(2);
    expect(inputTitles()[1]).toContain("Slider");
  });

  it("adds a display block the same way", async () => {
    render(<Host />);
    const before = screen.getByTestId("canvas-display").querySelectorAll(".mlp-canvas-item").length;
    await userEvent.click(screen.getByTestId("palette-image"));
    expect(
      screen.getByTestId("canvas-display").querySelectorAll(".mlp-canvas-item"),
    ).toHaveLength(before + 1);
  });

  it("removes a field", async () => {
    render(<Host />);
    await userEvent.click(screen.getByTestId("palette-tags"));
    expect(inputRows()).toHaveLength(2);
    await userEvent.click(screen.getByTestId("canvas-inputs-remove-1"));
    expect(inputRows()).toHaveLength(1);
  });

  it("dropping the same type twice makes two distinct fields", async () => {
    const seen = vi.fn();
    render(<Host onSchema={seen} />);
    await userEvent.click(screen.getByTestId("palette-rating"));
    await userEvent.click(screen.getByTestId("palette-rating"));
    const schema = seen.mock.calls.at(-1)![0] as TemplateSchema;
    const ids = schema.inputs.map((i) => i.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(screen.queryByTestId("builder-errors")).not.toBeInTheDocument();
  });
});

// --- reordering -------------------------------------------------------------

describe("drag-and-drop reordering", () => {
  it("reorders with the ↓ button", async () => {
    render(<Host />);
    await userEvent.click(screen.getByTestId("palette-tags"));
    const before = inputTitles();
    await userEvent.click(screen.getByTestId("canvas-inputs-down-0"));
    expect(inputTitles()).toEqual([before[1], before[0]]);
  });

  it("reorders by dragging one row onto another", async () => {
    render(<Host />);
    await userEvent.click(screen.getByTestId("palette-tags"));
    const before = inputTitles();
    const data = new Map<string, string>();
    const dataTransfer = {
      setData: (k: string, v: string) => data.set(k, v),
      getData: (k: string) => data.get(k) ?? "",
      effectAllowed: "move",
    };
    fireEvent.dragStart(screen.getByTestId("canvas-inputs-head-1"), { dataTransfer });
    fireEvent.drop(screen.getByTestId("canvas-inputs-item-0"), { dataTransfer });
    expect(inputTitles()).toEqual([before[1], before[0]]);
  });

  it("reorders from the keyboard with Alt+ArrowDown", async () => {
    render(<Host />);
    await userEvent.click(screen.getByTestId("palette-tags"));
    const before = inputTitles();
    const head = screen.getByTestId("canvas-inputs-head-0");
    head.focus();
    await userEvent.keyboard("{Alt>}{ArrowDown}{/Alt}");
    expect(inputTitles()).toEqual([before[1], before[0]]);
  });

  it("cannot move the first row up or the last row down", async () => {
    render(<Host />);
    await userEvent.click(screen.getByTestId("palette-tags"));
    expect(screen.getByTestId("canvas-inputs-up-0")).toBeDisabled();
    expect(screen.getByTestId("canvas-inputs-down-1")).toBeDisabled();
  });
});

// --- inline editing ---------------------------------------------------------

describe("inline field editing", () => {
  it("edits a label, options and required through the inspector", async () => {
    const seen = vi.fn();
    render(<Host onSchema={seen} />);
    await userEvent.click(screen.getByTestId("canvas-inputs-head-0"));

    const label = screen.getByTestId("inspector-label");
    await userEvent.clear(label);
    await userEvent.type(label, "Is it spam?");

    const options = screen.getByTestId("inspector-options");
    await userEvent.clear(options);
    await userEvent.type(options, "spam\nham\nunsure");

    await userEvent.click(screen.getByTestId("inspector-required"));

    const schema = seen.mock.calls.at(-1)![0] as TemplateSchema;
    expect(schema.inputs[0].label).toBe("Is it spam?");
    expect(schema.inputs[0].options).toEqual(["spam", "ham", "unsure"]);
    expect(schema.inputs[0].required).toBe(false);
  });

  it("offers allow_other only where the type supports it (§2.1)", async () => {
    render(<Host />);
    await userEvent.click(screen.getByTestId("canvas-inputs-head-0")); // radio
    expect(screen.getByTestId("inspector-allow-other")).toBeInTheDocument();

    await userEvent.click(screen.getByTestId("palette-tags"));
    await userEvent.click(screen.getByTestId("canvas-inputs-head-1")); // tags
    expect(screen.queryByTestId("inspector-allow-other")).not.toBeInTheDocument();
  });

  it("offers numeric bounds for a slider and a scale for a rating", async () => {
    render(<Host />);
    await userEvent.click(screen.getByTestId("palette-slider"));
    await userEvent.click(screen.getByTestId("canvas-inputs-head-1"));
    expect(screen.getByTestId("inspector-min")).toBeInTheDocument();
    expect(screen.queryByTestId("inspector-scale-max")).not.toBeInTheDocument();

    await userEvent.click(screen.getByTestId("palette-rating"));
    await userEvent.click(screen.getByTestId("canvas-inputs-head-2"));
    expect(screen.getByTestId("inspector-scale-max")).toBeInTheDocument();
    expect(screen.queryByTestId("inspector-min")).not.toBeInTheDocument();
  });

  it("surfaces a hotkey conflict as you type it and blocks save (§2.4)", async () => {
    render(<Host onSave={vi.fn()} />);
    await userEvent.click(screen.getByTestId("canvas-inputs-head-0"));
    await userEvent.type(screen.getByTestId("inspector-hotkeys"), "s, 1");

    const errors = screen.getByTestId("builder-errors");
    expect(within(errors).getByText(/reserved key/)).toBeInTheDocument();
    expect(screen.getByTestId("builder-save")).toBeDisabled();
  });

  it("blocks save on an invalid field and re-enables it once fixed", async () => {
    render(<Host onSave={vi.fn()} />);
    await userEvent.click(screen.getByTestId("canvas-inputs-head-0"));
    const options = screen.getByTestId("inspector-options");
    await userEvent.clear(options);
    await userEvent.type(options, "only-one");
    expect(screen.getByTestId("builder-save")).toBeDisabled();

    await userEvent.type(options, "\nand-another");
    expect(screen.getByTestId("builder-save")).toBeEnabled();
  });

  it("edits a display block's source and render options", async () => {
    const seen = vi.fn();
    render(<Host onSchema={seen} />);
    await userEvent.click(screen.getByTestId("canvas-display-head-0"));
    const source = screen.getByTestId("inspector-source");
    await userEvent.clear(source);
    await userEvent.type(source, "$unit.passage");
    await userEvent.click(screen.getByTestId("inspector-render-collapsible"));

    const schema = seen.mock.calls.at(-1)![0] as TemplateSchema;
    expect(schema.display![0].source).toBe("$unit.passage");
    expect(schema.display![0].render).toEqual({ collapsible: true });
  });
});

// --- two views, one document ------------------------------------------------

describe("builder and JSON are two views of one document (§2.5)", () => {
  it("shows the canvas edits in the JSON view", async () => {
    render(<Host />);
    await userEvent.click(screen.getByTestId("palette-rating"));
    await userEvent.click(screen.getByTestId("view-json"));

    const json = screen.getByTestId("builder-json") as HTMLTextAreaElement;
    const parsed = JSON.parse(json.value) as TemplateSchema;
    expect(parsed.inputs.map((i) => i.type)).toContain("rating");
  });

  it("shows JSON edits back on the canvas", async () => {
    render(<Host />);
    await userEvent.click(screen.getByTestId("view-json"));
    const json = screen.getByTestId("builder-json") as HTMLTextAreaElement;

    const edited: TemplateSchema = {
      ...JSON.parse(json.value),
      inputs: [
        { id: "verdict", type: "radio", label: "Verdict", options: ["a", "b"], required: true },
        { id: "score", type: "slider", label: "Score", min: 0, max: 10, step: 1 },
      ],
    };
    fireEvent.change(json, { target: { value: JSON.stringify(edited, null, 2) } });

    await userEvent.click(screen.getByTestId("view-builder"));
    expect(inputTitles()[1]).toContain("Score");
  });

  it("reports malformed JSON without discarding the document", async () => {
    render(<Host />);
    await userEvent.click(screen.getByTestId("view-json"));
    const json = screen.getByTestId("builder-json") as HTMLTextAreaElement;
    fireEvent.change(json, { target: { value: "{ not json" } });

    expect(screen.getByTestId("builder-errors")).toHaveTextContent("JSON:");
    await userEvent.click(screen.getByTestId("view-builder"));
    // The canvas still holds the last good document.
    expect(inputRows().length).toBeGreaterThan(0);
  });
});

// --- layout -----------------------------------------------------------------

describe("preview placement", () => {
  it("puts the preview beside the editor in the same shell, not after it", () => {
    render(
      <TemplateBuilder schema={blankTemplate()} onChange={() => {}} />, // showPreview defaults on
    );
    const shell = screen.getByTestId("builder-shell");
    const preview = screen.getByTestId("builder-preview");
    // Both the work column and the preview are direct children of the shell, so
    // one CSS rule decides side-by-side vs stacked — there is no JS branch and
    // nothing to keep in sync with the window size.
    expect(preview.parentElement).toBe(shell);
    expect(shell).toHaveClass("mlp-builder-shell-split");
    expect(shell.querySelector(".mlp-builder-work")).not.toBeNull();
  });

  it("keeps the preview beside the JSON view too", async () => {
    render(<TemplateBuilder schema={blankTemplate()} onChange={() => {}} />);
    await userEvent.click(screen.getByTestId("view-json"));
    expect(screen.getByTestId("builder-json")).toBeInTheDocument();
    expect(screen.getByTestId("builder-preview").parentElement).toBe(
      screen.getByTestId("builder-shell"),
    );
  });

  it("drops the split when the preview is hidden", () => {
    render(
      <TemplateBuilder schema={blankTemplate()} onChange={() => {}} showPreview={false} />,
    );
    expect(screen.queryByTestId("builder-preview")).not.toBeInTheDocument();
    expect(screen.getByTestId("builder-shell")).not.toHaveClass("mlp-builder-shell-split");
  });
});

// --- server errors ----------------------------------------------------------

describe("server errors", () => {
  it("shows what the backend rejected, verbatim", () => {
    render(
      <TemplateBuilder
        schema={blankTemplate()}
        onChange={() => {}}
        serverErrors={["inputs/0: 'type' is a required property"]}
        showPreview={false}
      />,
    );
    expect(screen.getByTestId("builder-errors")).toHaveTextContent(
      "'type' is a required property",
    );
  });
});

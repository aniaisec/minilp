// Pure builder operations (§2.5, §11) — the drag-and-drop mechanics and the
// "the builder writes the canonical schema" contract, tested without rendering.

import { describe, expect, it } from "vitest";

import { assignHotkeys } from "../../../hotkeys/assign";
import { INPUT_WIDGETS } from "../../../widgets/registry";
import {
  DISPLAY_PALETTE,
  INPUT_PALETTE,
  blankTemplate,
  cleanSchema,
  moveItem,
  newDisplay,
  newInput,
  referencedKeys,
  removeAt,
  replaceAt,
  uniqueId,
} from "./schema";
import { validateSchema } from "./validate";

describe("palette", () => {
  it("only offers types the renderer can actually draw (§2.6)", () => {
    for (const entry of INPUT_PALETTE) {
      expect(INPUT_WIDGETS[entry.type as keyof typeof INPUT_WIDGETS], entry.type).toBeTruthy();
    }
  });

  it("every palette entry produces a valid field on its own", () => {
    for (const entry of INPUT_PALETTE) {
      const schema = { ...blankTemplate(), inputs: [newInput(entry.type as never, [])] };
      expect(validateSchema(schema), `${entry.type}: ${validateSchema(schema).join("; ")}`)
        .toEqual([]);
    }
  });

  it("every display palette entry produces a valid block on its own", () => {
    for (const entry of DISPLAY_PALETTE) {
      const schema = { ...blankTemplate(), display: [newDisplay(entry.type as never, [])] };
      expect(validateSchema(schema), `${entry.type}`).toEqual([]);
    }
  });

  it("a canvas holding one of everything is still valid", () => {
    const inputs: ReturnType<typeof newInput>[] = [];
    for (const entry of INPUT_PALETTE) {
      inputs.push(newInput(entry.type as never, inputs.map((i) => i.id)));
    }
    const display: ReturnType<typeof newDisplay>[] = [];
    for (const entry of DISPLAY_PALETTE) {
      display.push(newDisplay(entry.type as never, referencedKeys({ ...blankTemplate(), display })));
    }
    const schema = { ...blankTemplate(), inputs, display };
    expect(validateSchema(schema)).toEqual([]);
  });
});

describe("unique ids", () => {
  it("suffixes a collision rather than overwriting", () => {
    expect(uniqueId("rating", [])).toBe("rating");
    expect(uniqueId("rating", ["rating"])).toBe("rating_2");
    expect(uniqueId("rating", ["rating", "rating_2"])).toBe("rating_3");
  });

  it("dropping the same type twice yields two distinct fields", () => {
    const first = newInput("rating", []);
    const second = newInput("rating", [first.id]);
    expect(second.id).not.toBe(first.id);
    expect(validateSchema({ ...blankTemplate(), inputs: [first, second] })).toEqual([]);
  });
});

describe("reordering (drag-and-drop mechanics)", () => {
  const list = ["a", "b", "c", "d"];

  it("moves an item forward and back", () => {
    expect(moveItem(list, 0, 2)).toEqual(["b", "c", "a", "d"]);
    expect(moveItem(list, 3, 0)).toEqual(["d", "a", "b", "c"]);
  });

  it("is a no-op for an unchanged or out-of-range move", () => {
    expect(moveItem(list, 1, 1)).toBe(list);
    expect(moveItem(list, 0, -1)).toBe(list);
    expect(moveItem(list, 0, 9)).toBe(list);
  });

  it("removes and replaces without mutating the original", () => {
    expect(removeAt(list, 1)).toEqual(["a", "c", "d"]);
    expect(replaceAt(list, 1, "B")).toEqual(["a", "B", "c", "d"]);
    expect(list).toEqual(["a", "b", "c", "d"]);
  });

  it("reordering inputs re-assigns auto hotkeys (§2.4) without conflicts", () => {
    const inputs = [
      { id: "one", type: "radio" as const, options: ["x", "y"] },
      { id: "two", type: "radio" as const, options: ["p", "q"] },
    ];
    const before = assignHotkeys(inputs);
    const after = assignHotkeys(moveItem(inputs, 0, 1));
    expect(before.errors).toEqual([]);
    expect(after.errors).toEqual([]);
    // The first input on the canvas holds the digits, whichever it now is.
    expect(Object.values(before.byInput.one.options)).toEqual(["1", "2"]);
    expect(Object.values(after.byInput.two.options)).toEqual(["1", "2"]);
  });
});

describe("cleanSchema", () => {
  it("drops builder-only emptiness before saving", () => {
    const cleaned = cleanSchema({
      name: "t",
      description: "",
      display: [{ type: "text", source: "$unit.text", render: {}, optional: false }],
      inputs: [
        {
          id: "a",
          type: "radio",
          label: "",
          options: ["x", "y"],
          hotkeys: "auto",
          allow_other: false,
        },
      ],
    });
    expect(cleaned.description).toBeUndefined();
    expect(cleaned.display![0].render).toBeUndefined();
    expect(cleaned.display![0].optional).toBeUndefined();
    expect(cleaned.inputs[0].label).toBeUndefined();
    expect(cleaned.inputs[0].hotkeys).toBeUndefined();
    expect(cleaned.inputs[0].allow_other).toBeUndefined();
  });

  it("keeps everything that carries meaning", () => {
    const cleaned = cleanSchema({
      name: "t",
      display: [{ type: "image", source: "$unit.img", render: { fit: "contain" }, optional: true }],
      inputs: [
        { id: "a", type: "radio", label: "Verdict", options: ["x", "y"], hotkeys: ["x", "y"] },
      ],
    });
    expect(cleaned.display![0].render).toEqual({ fit: "contain" });
    expect(cleaned.display![0].optional).toBe(true);
    expect(cleaned.inputs[0].hotkeys).toEqual(["x", "y"]);
  });

  it("round-trips a blank template unchanged in meaning", () => {
    expect(validateSchema(cleanSchema(blankTemplate()))).toEqual([]);
  });
});

describe("validation mirrors the backend rules the author trips over", () => {
  const withInput = (field: Record<string, unknown>) => ({
    ...blankTemplate(),
    inputs: [field as never],
  });

  it("catches a select with one option", () => {
    const errs = validateSchema(withInput({ id: "s", type: "select", options: ["only"] }));
    expect(errs.some((e) => e.includes("at least 2 options"))).toBe(true);
  });

  it("catches a slider without bounds", () => {
    const errs = validateSchema(withInput({ id: "s", type: "slider" }));
    expect(errs.some((e) => e.includes("requires both min and max"))).toBe(true);
  });

  it("catches a reserved hotkey (§2.4 invariant 4)", () => {
    const errs = validateSchema(
      withInput({ id: "v", type: "radio", options: ["a", "b"], hotkeys: ["s", "1"] }),
    );
    expect(errs.some((e) => e.includes("reserved key"))).toBe(true);
  });

  it("catches a duplicate input id", () => {
    const errs = validateSchema({
      ...blankTemplate(),
      inputs: [
        { id: "dup", type: "radio", options: ["a", "b"] },
        { id: "dup", type: "free_text" },
      ],
    });
    expect(errs.some((e) => e.includes("duplicate input id"))).toBe(true);
  });

  it("catches a source that isn't a $unit reference", () => {
    const errs = validateSchema({
      ...blankTemplate(),
      display: [{ type: "text", source: "text" }],
    });
    expect(errs.some((e) => e.includes("$unit."))).toBe(true);
  });

  it("catches an invalid render option for the block type", () => {
    const errs = validateSchema({
      ...blankTemplate(),
      display: [{ type: "text", source: "$unit.text", render: { fit: "contain" } }],
    });
    expect(errs.some((e) => e.includes("render option 'fit' is not valid"))).toBe(true);
  });

  it("accepts a well-formed template", () => {
    expect(validateSchema(blankTemplate())).toEqual([]);
  });
});

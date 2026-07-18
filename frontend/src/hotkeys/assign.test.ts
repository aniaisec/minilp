import { describe, expect, it } from "vitest";
import type { InputField } from "../api/types";
import {
  IMAGE_CLASSIFICATION,
  SIDE_BY_SIDE,
  SUMMARY_QUALITY,
  TEXT_SENTIMENT,
  TOXICITY_REVIEW,
} from "../fixtures/gallery";
import { assignHotkeys } from "./assign";

describe("assignHotkeys — gallery parity with backend", () => {
  it("side-by-side: explicit arrow keys, normalized", () => {
    const a = assignHotkeys(SIDE_BY_SIDE.inputs);
    expect(a.errors).toEqual([]);
    expect(a.byInput.choice.options).toEqual({ Left: "left", Tie: "down", Right: "right" });
  });

  it("image-classification: first radio gets digits, Other gets 'o'", () => {
    const a = assignHotkeys(IMAGE_CLASSIFICATION.inputs);
    expect(a.errors).toEqual([]);
    expect(a.byInput.category.options).toEqual({ cat: "1", dog: "2", bird: "3" });
    expect(a.byInput.category.other).toBe("o");
  });

  it("text-sentiment: first radio digits, second (likert) draws letters skipping reserved", () => {
    const a = assignHotkeys(TEXT_SENTIMENT.inputs);
    expect(a.errors).toEqual([]);
    expect(a.byInput.sentiment.options).toEqual({ positive: "1", neutral: "2", negative: "3" });
    // likert 1..5 → letters a,b,c,e,f ('d' is reserved for dark mode)
    expect(a.byInput.confidence.options).toEqual({ "1": "a", "2": "b", "3": "c", "4": "e", "5": "f" });
  });

  it("summary-quality: three likerts share one letter pool without collision", () => {
    const a = assignHotkeys(SUMMARY_QUALITY.inputs);
    expect(a.errors).toEqual([]);
    expect(Object.values(a.byInput.faithfulness.options)).toEqual(["1", "2", "3", "4", "5"]);
    expect(Object.values(a.byInput.coverage.options)).toEqual(["a", "b", "c", "e", "f"]);
    expect(Object.values(a.byInput.fluency.options)).toEqual(["h", "i", "j", "k", "l"]);
  });

  it("toxicity: checkbox digits + Other, radio letters", () => {
    const a = assignHotkeys(TOXICITY_REVIEW.inputs);
    expect(a.errors).toEqual([]);
    expect(a.byInput.violations.other).toBe("o");
    expect(Object.values(a.byInput.violations.options)).toEqual(["1", "2", "3", "4", "5"]);
    expect(a.byInput.severity.options).toEqual({ none: "a", low: "b", medium: "c", high: "e" });
  });

  it("no interactive element shares a key within a template", () => {
    for (const inputs of [
      SIDE_BY_SIDE.inputs,
      IMAGE_CLASSIFICATION.inputs,
      TEXT_SENTIMENT.inputs,
      SUMMARY_QUALITY.inputs,
      TOXICITY_REVIEW.inputs,
    ]) {
      const a = assignHotkeys(inputs);
      const keys: string[] = [];
      for (const entry of Object.values(a.byInput)) {
        keys.push(...Object.values(entry.options));
        if (entry.other) keys.push(entry.other);
      }
      expect(new Set(keys).size).toBe(keys.length);
    }
  });
});

describe("assignHotkeys — conflict detection", () => {
  it("flags duplicate explicit hotkeys", () => {
    const inputs: InputField[] = [
      { id: "x", type: "radio", options: ["a", "b"], hotkeys: ["1", "1"] },
    ];
    const a = assignHotkeys(inputs);
    expect(a.errors.some((e) => e.includes("duplicate"))).toBe(true);
  });

  it("flags reserved-key collisions", () => {
    const inputs: InputField[] = [
      { id: "x", type: "radio", options: ["a", "b"], hotkeys: ["s", "1"] },
    ];
    const a = assignHotkeys(inputs);
    expect(a.errors.some((e) => e.includes("reserved"))).toBe(true);
  });

  it("flags explicit hotkey/option length mismatch", () => {
    const inputs: InputField[] = [
      { id: "x", type: "radio", options: ["a", "b", "c"], hotkeys: ["1", "2"] },
    ];
    const a = assignHotkeys(inputs);
    expect(a.errors.some((e) => e.includes("!= option count"))).toBe(true);
  });
});

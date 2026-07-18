import { describe, expect, it } from "vitest";
import { IMAGE_CLASSIFICATION, SIDE_BY_SIDE, TOXICITY_REVIEW } from "../fixtures/gallery";
import { canonicalize } from "./canonical";

describe("canonicalize — panel_order variant (§2.7)", () => {
  it("AB: Left→A, Right→B, Tie unchanged", () => {
    expect(canonicalize(SIDE_BY_SIDE, { choice: "Left" }, "AB")).toEqual({ choice: "A" });
    expect(canonicalize(SIDE_BY_SIDE, { choice: "Right" }, "AB")).toEqual({ choice: "B" });
    expect(canonicalize(SIDE_BY_SIDE, { choice: "Tie" }, "AB")).toEqual({ choice: "Tie" });
  });

  it("BA: Left→B, Right→A (order flips)", () => {
    expect(canonicalize(SIDE_BY_SIDE, { choice: "Left" }, "BA")).toEqual({ choice: "B" });
    expect(canonicalize(SIDE_BY_SIDE, { choice: "Right" }, "BA")).toEqual({ choice: "A" });
  });
});

describe("canonicalize — allow_other (§2.3)", () => {
  it("radio strips the other: prefix", () => {
    expect(canonicalize(IMAGE_CLASSIFICATION, { category: "other:capybara" }, null)).toEqual({
      category: "capybara",
    });
  });

  it("preset radio value passes through unchanged", () => {
    expect(canonicalize(IMAGE_CLASSIFICATION, { category: "cat" }, null)).toEqual({
      category: "cat",
    });
  });

  it("checkbox strips other: element-wise, keeps presets", () => {
    expect(
      canonicalize(TOXICITY_REVIEW, { violations: ["hate", "other:spam"], severity: "high" }, null),
    ).toEqual({ violations: ["hate", "spam"], severity: "high" });
  });
});

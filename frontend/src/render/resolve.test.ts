import { describe, expect, it } from "vitest";
import { SIDE_BY_SIDE } from "../fixtures/gallery";
import { orderedPanelSources, variantString } from "./resolve";

const panelBlock = SIDE_BY_SIDE.display![1];

describe("orderedPanelSources — variant-driven panel order (§2.7)", () => {
  it("AB keeps natural order", () => {
    expect(orderedPanelSources(panelBlock, "AB")).toEqual([
      { source: "$unit.response_a", item: "A" },
      { source: "$unit.response_b", item: "B" },
    ]);
  });

  it("BA swaps the panels", () => {
    expect(orderedPanelSources(panelBlock, "BA")).toEqual([
      { source: "$unit.response_b", item: "B" },
      { source: "$unit.response_a", item: "A" },
    ]);
  });

  it("falls back to natural order when no variant", () => {
    expect(orderedPanelSources(panelBlock, null)).toEqual([
      { source: "$unit.response_a", item: "A" },
      { source: "$unit.response_b", item: "B" },
    ]);
  });
});

describe("variantString", () => {
  it("reads the variant dimension value", () => {
    expect(variantString(SIDE_BY_SIDE, { panel_order: "BA" })).toBe("BA");
    expect(variantString(SIDE_BY_SIDE, null)).toBeNull();
  });
});

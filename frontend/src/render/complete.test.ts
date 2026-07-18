import { describe, expect, it } from "vitest";
import {
  IMAGE_CLASSIFICATION,
  SIDE_BY_SIDE,
  SUMMARY_QUALITY,
  TEXT_SENTIMENT,
} from "../fixtures/gallery";
import { autoSubmitInputId, isComplete } from "./complete";

describe("isComplete — required gating (§2.3)", () => {
  it("side-by-side needs the single required choice", () => {
    expect(isComplete(SIDE_BY_SIDE, {})).toBe(false);
    expect(isComplete(SIDE_BY_SIDE, { choice: "Left" })).toBe(true);
  });

  it("text-sentiment: only sentiment is required; confidence optional", () => {
    expect(isComplete(TEXT_SENTIMENT, {})).toBe(false);
    expect(isComplete(TEXT_SENTIMENT, { sentiment: "positive" })).toBe(true);
  });

  it("summary-quality needs all three likerts", () => {
    expect(isComplete(SUMMARY_QUALITY, { faithfulness: 3, coverage: 4 })).toBe(false);
    expect(isComplete(SUMMARY_QUALITY, { faithfulness: 3, coverage: 4, fluency: 5 })).toBe(true);
  });

  it("an Other selection with empty text is incomplete", () => {
    expect(isComplete(IMAGE_CLASSIFICATION, { category: "other:" })).toBe(false);
    expect(isComplete(IMAGE_CLASSIFICATION, { category: "other:fox" })).toBe(true);
  });
});

describe("autoSubmitInputId — single-input auto-submit (§2.4)", () => {
  it("fires for single-input choice templates", () => {
    expect(autoSubmitInputId(SIDE_BY_SIDE)).toBe("choice");
    expect(autoSubmitInputId(IMAGE_CLASSIFICATION)).toBe("category");
  });

  it("does not fire when there are multiple inputs", () => {
    expect(autoSubmitInputId(TEXT_SENTIMENT)).toBeNull();
    expect(autoSubmitInputId(SUMMARY_QUALITY)).toBeNull();
  });
});

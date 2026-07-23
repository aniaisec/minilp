import { describe, expect, it } from "vitest";

import { ci, eta, pct, ranked, total } from "./format";

describe("pct", () => {
  it("formats proportions as percentages", () => {
    expect(pct(0.667)).toBe("66.7%");
    expect(pct(1)).toBe("100.0%");
    expect(pct(0, 0)).toBe("0%");
  });
  it("renders a dash for missing values", () => {
    expect(pct(null)).toBe("—");
    expect(pct(undefined)).toBe("—");
  });
});

describe("eta", () => {
  it("scales units from minutes to days", () => {
    expect(eta(0.5)).toBe("30m");
    expect(eta(5)).toBe("5.0h");
    expect(eta(50)).toBe("2.1d");
  });
  it("dashes out an undefined or infinite ETA (stalled project)", () => {
    expect(eta(null)).toBe("—");
    expect(eta(Infinity)).toBe("—");
  });
});

describe("ci", () => {
  it("renders estimate with its interval", () => {
    expect(ci({ estimate: 0.75, ci_low: 0.6, ci_high: 0.86, n: 8 })).toBe("0.75 [0.60–0.86]");
    expect(ci(null)).toBe("—");
  });
});

describe("ranked / total", () => {
  it("orders histogram entries by count desc and sums them", () => {
    const h = { cat: 3, dog: 5, bird: 1 };
    expect(ranked(h)).toEqual([
      ["dog", 5],
      ["cat", 3],
      ["bird", 1],
    ]);
    expect(total(h)).toBe(9);
  });
});

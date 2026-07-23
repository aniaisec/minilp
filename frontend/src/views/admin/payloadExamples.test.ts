import { describe, expect, it } from "vitest";

import type { TemplateSample } from "../../api/types";
import { jsonExample, missingRequiredFields, tsvExample } from "./payloadExamples";

const sample: TemplateSample = {
  template_id: 1,
  saved: false,
  sample: { image_url: "http://x/1.png", context: "a cat" },
  fields: { required: ["image_url"], optional: ["context"] },
};

describe("jsonExample", () => {
  it("wraps the sample payload in a one-element array", () => {
    const parsed = JSON.parse(jsonExample(sample));
    expect(parsed).toEqual([{ payload: { image_url: "http://x/1.png", context: "a cat" }, priority: 0 }]);
  });
});

describe("tsvExample", () => {
  it("puts required fields first, adds a priority column, and one data row", () => {
    const [header, row] = tsvExample(sample).split("\n");
    expect(header).toBe("image_url\tcontext\tpriority");
    expect(row).toBe("http://x/1.png\ta cat\t0");
  });
});

describe("missingRequiredFields", () => {
  it("flags a TSV header missing a required column", () => {
    expect(missingRequiredFields("context\nfoo", "tsv", ["image_url"])).toEqual(["image_url"]);
    expect(missingRequiredFields("image_url\tcontext\nx\ty", "tsv", ["image_url"])).toEqual([]);
  });
  it("flags a JSON payload missing a required key", () => {
    expect(
      missingRequiredFields('[{"payload": {"context": "x"}}]', "json", ["image_url"]),
    ).toEqual(["image_url"]);
    expect(
      missingRequiredFields('[{"payload": {"image_url": "x"}}]', "json", ["image_url"]),
    ).toEqual([]);
  });
  it("stays quiet on empty or unparseable content (backend re-checks)", () => {
    expect(missingRequiredFields("", "json", ["image_url"])).toEqual([]);
    expect(missingRequiredFields("{bad", "json", ["image_url"])).toEqual([]);
  });
});

// The project-section model (UX plan, phase 3). Pure functions, tested here so
// the routing and the state pill can't drift without something going red.

import { describe, expect, it } from "vitest";

import type { Progress } from "../../api/types";
import {
  DEFAULT_PROJECT_TAB,
  PROJECT_TABS,
  PROJECT_TAB_GROUPS,
  projectCompletion,
  projectState,
  projectTabHref,
  projectTabLabel,
  resolveProjectTab,
} from "./projectTabs";

function funnel(over: Partial<Progress["funnel"]> = {}): Progress["funnel"] {
  return { pending: 0, in_progress: 0, labeled: 0, finalized: 0, total: 0, escalated: 0, ...over };
}

describe("the section model", () => {
  it("keeps every section in exactly one group", () => {
    const ids = PROJECT_TAB_GROUPS.flatMap((g) => g.items.map((i) => i.id));
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids).toHaveLength(PROJECT_TABS.length);
  });

  it("names every group", () => {
    for (const group of PROJECT_TAB_GROUPS) expect(group.heading).toBeTruthy();
  });

  it("labels every section", () => {
    for (const t of PROJECT_TABS) expect(projectTabLabel(t.id)).toBe(t.label);
  });
});

describe("resolveProjectTab", () => {
  it("accepts every known slug", () => {
    for (const t of PROJECT_TABS) expect(resolveProjectTab(t.id)).toBe(t.id);
  });

  it("falls back to the default for a missing or unknown segment", () => {
    // A typo, a link from an older build, a truncated paste — none of them
    // should produce a blank screen.
    expect(resolveProjectTab(undefined)).toBe(DEFAULT_PROJECT_TAB);
    expect(resolveProjectTab("")).toBe(DEFAULT_PROJECT_TAB);
    expect(resolveProjectTab("unitz")).toBe(DEFAULT_PROJECT_TAB);
    expect(resolveProjectTab("__proto__")).toBe(DEFAULT_PROJECT_TAB);
  });
});

describe("projectTabHref", () => {
  it("names the section in the URL", () => {
    expect(projectTabHref(3, "units")).toBe("#/admin/project/3/units");
  });
});

describe("projectState", () => {
  it("says so when there is nothing to do yet", () => {
    expect(projectState(funnel())).toEqual({ label: "No tasks", tone: "muted" });
  });

  it("distinguishes a loaded-but-untouched project from a running one", () => {
    expect(projectState(funnel({ total: 10, pending: 10 })).label).toBe("Not started");
    expect(projectState(funnel({ total: 10, pending: 9, in_progress: 1 })).label).toBe(
      "In progress",
    );
    // Labeled-but-not-finalized still counts as started: work has happened.
    expect(projectState(funnel({ total: 10, pending: 9, labeled: 1 })).label).toBe("In progress");
  });

  it("is complete only when every unit is finalized", () => {
    expect(projectState(funnel({ total: 10, finalized: 9, pending: 1 })).label).toBe("In progress");
    expect(projectState(funnel({ total: 10, finalized: 10 }))).toEqual({
      label: "Complete",
      tone: "ok",
    });
  });
});

describe("projectCompletion", () => {
  it("is the finalized share, and zero rather than NaN on an empty project", () => {
    expect(projectCompletion(funnel({ total: 200, finalized: 50 }))).toBe(0.25);
    expect(projectCompletion(funnel())).toBe(0);
  });
});

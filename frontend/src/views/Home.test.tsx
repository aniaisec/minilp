// M8 acceptance — the annotator home (§11, §12).
//
// The claim under test that matters most: **table and cards render from one
// fetch and can never disagree**. Both presentations are asserted against the
// same `/tasks/available` response, which is the endpoint that already applies
// the assignment engine's own exclusion — so if these numbers are right, the
// home page reconciles with what the annotator will actually be served.

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AvailableProject } from "../api/types";
import { HOME_VIEW_KEY, Home, homeUrl, projectUrl, readHomeView } from "./Home";

function project(over: Partial<AvailableProject> = {}): AvailableProject {
  return {
    project_id: 1,
    name: "Sentiment",
    description: "Label the tone",
    template_id: 3,
    template_version: 1,
    labels_per_unit: 2,
    available_labels: 12,
    open_units: 6,
    your_labels: 4,
    eligible: true,
    blocked_reason: null,
    ...over,
  };
}

function mockClient(projects: AvailableProject[]) {
  return {
    availableWork: vi.fn().mockResolvedValue({ annotator_id: 9, projects }),
  } as unknown as Parameters<typeof Home>[0]["client"] & {
    availableWork: ReturnType<typeof vi.fn>;
  };
}

function renderHome(projects: AvailableProject[], initialView: "table" | "cards" = "table") {
  const client = mockClient(projects);
  render(<Home client={client} annotator={9} apiKey="k" initialView={initialView} />);
  return client;
}

beforeEach(() => {
  try {
    window.localStorage.clear();
  } catch {
    /* no storage in this environment */
  }
});

// --- one fetch, two presentations (§12 M8 acceptance) ------------------------

describe("home renders both presentations from a single fetch", () => {
  const projects = [
    project({ project_id: 1, name: "Sentiment", available_labels: 12, open_units: 6, your_labels: 4 }),
    project({ project_id: 2, name: "Images", available_labels: 3, open_units: 3, your_labels: 0 }),
  ];

  it("shows the same per-project counts in the table and in the cards", async () => {
    const client = renderHome(projects);
    await screen.findByTestId("home-table");
    expect(client.availableWork).toHaveBeenCalledTimes(1);

    const tableCounts = projects.map(
      (p) => screen.getByTestId(`home-row-${p.project_id}-available`).textContent,
    );

    fireEvent.click(screen.getByTestId("view-cards"));
    await screen.findByTestId("home-cards");
    const cardCounts = projects.map(
      (p) => screen.getByTestId(`home-card-${p.project_id}-available`).textContent,
    );

    expect(cardCounts).toEqual(tableCounts);
    expect(cardCounts).toEqual(["12", "3"]);
    // Toggling the view must not re-ask the server: one fetch, two renderings.
    expect(client.availableWork).toHaveBeenCalledTimes(1);
  });

  it("counts the whole queue in the summary line", async () => {
    renderHome(projects);
    const summary = await screen.findByTestId("home-summary");
    expect(summary.textContent).toContain("15 labels available");
    expect(summary.textContent).toContain("4 submitted by you");
  });

  it("shows every project in both views, including blocked ones", async () => {
    renderHome([...projects, project({ project_id: 3, name: "Locked", eligible: false, blocked_reason: "below min_reputation" })]);
    await screen.findByTestId("home-table");
    expect(screen.getByTestId("home-row-3")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("view-cards"));
    await screen.findByTestId("home-cards");
    const card = screen.getByTestId("home-card-3");
    expect(within(card).getByTestId("home-card-3-note").textContent).toContain(
      "below min_reputation",
    );
  });
});

// --- the view toggle is remembered (§11) -------------------------------------

describe("the view preference is persisted like the theme", () => {
  it("writes the choice to localStorage and reads it back", async () => {
    renderHome([project()]);
    await screen.findByTestId("home-table");

    fireEvent.click(screen.getByTestId("view-cards"));
    await screen.findByTestId("home-cards");
    expect(window.localStorage.getItem(HOME_VIEW_KEY)).toBe("cards");
    expect(readHomeView()).toBe("cards");
  });

  it("the stored preference beats the initial prop on a later visit", async () => {
    window.localStorage.setItem(HOME_VIEW_KEY, "cards");
    renderHome([project()], "table");
    expect(await screen.findByTestId("home-cards")).toBeInTheDocument();
    expect(screen.queryByTestId("home-table")).toBeNull();
  });

  it("falls back to the default when the stored value is nonsense", () => {
    window.localStorage.setItem(HOME_VIEW_KEY, "hologram");
    expect(readHomeView("table")).toBe("table");
  });

  it("marks the active view for assistive tech, not only visually", async () => {
    renderHome([project()]);
    await screen.findByTestId("home-table");
    expect(screen.getByTestId("view-table")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("view-cards")).toHaveAttribute("aria-pressed", "false");
  });
});

// --- the two emptinesses (§11) -----------------------------------------------

describe("empty states distinguish 'nothing exists' from 'you finished everything'", () => {
  it("says no projects exist when the list is empty", async () => {
    renderHome([]);
    const empty = await screen.findByTestId("home-empty");
    expect(empty.textContent).toContain("No projects yet");
    expect(screen.queryByTestId("home-drained")).toBeNull();
  });

  it("says you are caught up when projects exist but none has work for you", async () => {
    renderHome([project({ available_labels: 0, open_units: 0, your_labels: 20 })]);
    const drained = await screen.findByTestId("home-drained");
    expect(drained.textContent).toContain("All caught up");
    expect(drained.textContent).toContain("20");
    expect(screen.queryByTestId("home-empty")).toBeNull();
  });

  it("shows neither banner while work remains", async () => {
    renderHome([project({ available_labels: 5 })]);
    await screen.findByTestId("home-table");
    expect(screen.queryByTestId("home-empty")).toBeNull();
    expect(screen.queryByTestId("home-drained")).toBeNull();
  });
});

// --- per-project affordances -------------------------------------------------

describe("a project row/card reflects whether it can be worked", () => {
  it("disables the button and explains why when blocked", async () => {
    renderHome([project({ eligible: false, blocked_reason: "annotator is paused" })]);
    await screen.findByTestId("home-table");
    const row = screen.getByTestId("home-row-1");
    expect(within(row).getByRole("button")).toBeDisabled();
    expect(row.textContent).toContain("annotator is paused");
  });

  it("says Done rather than Label when a project is drained", async () => {
    renderHome([project({ available_labels: 0 })]);
    await screen.findByTestId("home-table");
    expect(within(screen.getByTestId("home-row-1")).getByRole("button").textContent).toBe("Done");
  });

  it("draws a fill bar from your labels against the work remaining", async () => {
    renderHome([project({ your_labels: 3, available_labels: 1 })], "cards");
    const card = await screen.findByTestId("home-card-1");
    // 3 of 4 done.
    expect(within(card).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "75");
  });

  it("surfaces a fetch failure instead of an eternal spinner", async () => {
    const client = {
      availableWork: vi.fn().mockRejectedValue(new Error("token expired")),
    } as unknown as Parameters<typeof Home>[0]["client"];
    render(<Home client={client} annotator={9} apiKey="k" />);
    await waitFor(() => expect(screen.getByTestId("home-error").textContent).toContain("token expired"));
  });
});

// --- the routes home and back ------------------------------------------------

describe("home and project URLs", () => {
  it("round-trips: home → project → home carries the annotator and key", () => {
    expect(homeUrl(9, "k")).toBe("?annotator=9&key=k");
    expect(projectUrl(4, 9, "k")).toBe("?project=4&annotator=9&key=k");
    // Leaving a project drops only the project — the identity survives.
    const params = new URLSearchParams(projectUrl(4, 9, "k").slice(1));
    params.delete("project");
    expect(`?${params.toString()}`).toBe(homeUrl(9, "k"));
  });

  it("omits an absent key rather than sending key=", () => {
    expect(homeUrl(9, "")).toBe("?annotator=9");
    expect(projectUrl(4, 9, "")).toBe("?project=4&annotator=9");
  });
});

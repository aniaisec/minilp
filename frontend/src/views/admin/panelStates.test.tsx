// Panel-level checks for the phase-5 rollout.
//
// The primitives have their own unit tests; these assert that the panels
// actually use them, which is the part a refactor silently loses. Three
// properties, checked on real panels against a stub client:
//
//   - a failed fetch renders an ErrorState, so it is announced rather than
//     sitting on the page as body text nobody is told about;
//   - an empty result renders an EmptyState *inside* the table, so the column
//     headers survive and the reader can see what they searched in;
//   - every table has an accessible name.
//
// Before phase 5 all three were false everywhere.

import { render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Roster } from "../../api/types";
import { Dashboard } from "./Dashboard";
import { RosterPanel } from "./RosterPanel";
import { UnitBrowser } from "./UnitBrowser";

const EMPTY_ROSTER: Roster = { project_id: 1, count: 0, annotators: [] };

const ROSTER: Roster = {
  project_id: 1,
  count: 1,
  annotators: [
    {
      annotator_id: 7,
      kind: "human",
      display_name: "ada",
      status: "active",
      pause_reason: null,
      reputation: 0.912,
      labels_valid: 41,
      labels_voided: 0,
      gold_passes: 8,
      gold_total: 9,
      gold_accuracy: 8 / 9,
    },
  ],
};

function client(over: Record<string, unknown> = {}) {
  return {
    getRoster: vi.fn().mockResolvedValue(ROSTER),
    listUnits: vi.fn().mockResolvedValue([]),
    listBatches: vi.fn().mockResolvedValue([]),
    listProjects: vi.fn().mockResolvedValue([]),
    ...over,
  } as never;
}

describe("error states", () => {
  it("announces a failed roster fetch as an alert", async () => {
    render(
      <RosterPanel client={client({ getRoster: vi.fn().mockRejectedValue(new Error("HTTP 503")) })} projectId={1} />,
    );
    const alert = await screen.findByRole("alert");
    // Our sentence and the server's detail are both present, and separate — the
    // reader gets something actionable even when the detail is machine noise.
    expect(within(alert).getByText("Could not load the roster")).toBeInTheDocument();
    expect(within(alert).getByText("HTTP 503")).toBeInTheDocument();
  });

  it("announces a failed project list as an alert", async () => {
    render(
      <Dashboard
        client={client({ listProjects: vi.fn().mockRejectedValue(new Error("nope")) })}
        apiKey=""
        onOpen={() => {}}
        onNew={() => {}}
      />,
    );
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("Could not load your projects")).toBeInTheDocument();
  });
});

describe("empty states", () => {
  it("keeps the roster's column headers when there are no annotators", async () => {
    render(<RosterPanel client={client({ getRoster: vi.fn().mockResolvedValue(EMPTY_ROSTER) })} projectId={1} />);
    expect(await screen.findByTestId("roster-empty")).toBeInTheDocument();
    // The point of an in-table empty state: the columns are still legible, so
    // the reader can see what would have been listed.
    expect(screen.getAllByRole("columnheader").length).toBeGreaterThan(0);
    expect(screen.getByRole("columnheader", { name: "reputation" })).toBeInTheDocument();
  });

  it("explains an empty unit list rather than collapsing the table", async () => {
    render(<UnitBrowser client={client()} projectId={1} />);
    const empty = await screen.findByTestId("units-empty");
    expect(within(empty).getByText("No units match these filters")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "payload" })).toBeInTheDocument();
  });

  it("offers a way out of the dashboard's empty state", async () => {
    const onNew = vi.fn();
    render(<Dashboard client={client()} apiKey="" onOpen={() => {}} onNew={onNew} />);
    const empty = await screen.findByTestId("dashboard-empty");
    // An empty state that only says "nothing here" is a dead end; this one
    // carries the action that fixes it.
    within(empty).getByRole("button", { name: "+ New project" }).click();
    expect(onNew).toHaveBeenCalled();
  });
});

describe("table naming", () => {
  it("names the roster table", async () => {
    render(<RosterPanel client={client()} projectId={1} />);
    await waitFor(() =>
      expect(
        screen.getByRole("table", { name: "Annotators on this project, with reputation and volume" }),
      ).toBeInTheDocument(),
    );
  });

  it("names the unit table and its action column", async () => {
    render(<UnitBrowser client={client()} projectId={1} />);
    await waitFor(() =>
      expect(
        screen.getByRole("table", { name: "Units in this project matching the current filters" }),
      ).toBeInTheDocument(),
    );
    expect(screen.getByRole("columnheader", { name: "Actions" })).toBeInTheDocument();
  });
});

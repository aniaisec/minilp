// Project view tests (UX plan, phase 3).
//
// These assert the properties the plan claims, not the markup that happens to
// implement them: the section round-trips through the URL, the grouping is
// available non-visually, `aria-current` follows the route, and the header
// states where the project actually stands. A snapshot test would pass while
// every one of those was broken.

import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Progress } from "../../api/types";
import { AdminApp } from "./AdminApp";
import { ProjectView } from "./ProjectView";
import { PROJECT_TAB_GROUPS } from "./projectTabs";

const PROJECT = {
  id: 1,
  name: "Image QA · furniture catalogue",
  template_id: 4,
  template_version: 3,
  labels_per_unit: 3,
  max_labels_per_unit: 5,
  gold_ratio: 0.08,
};

function progress(over: Partial<Progress["funnel"]> = {}): Progress {
  return {
    project_id: 1,
    labels_per_unit: 3,
    max_labels_per_unit: 5,
    funnel: {
      pending: 412,
      in_progress: 37,
      labeled: 289,
      finalized: 1104,
      total: 1842,
      escalated: 0,
      ...over,
    },
    slots: { open: 1273, leased: 37, filled: 4181, voided: 12 },
    labels_total: 4181,
    batches: [],
    variants: { dimension: null, balanced: true, values: [] },
    consensus: { complete_units: 0, keys: {} },
    throughput: {
      labels_per_hour: 42,
      window_hours: 24,
      labels_in_window: 1000,
      remaining_slots: 1273,
      eta_hours: 30,
    },
  };
}

/** jsdom has no `matchMedia`; the shell asks it about two breakpoints. */
function mockViewport(width: number) {
  window.matchMedia = ((query: string) => {
    const max = /max-width:\s*(\d+)px/.exec(query);
    return {
      matches: max ? width <= Number(max[1]) : false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    };
  }) as never;
}

/** A backend that answers the two requests the project chrome makes and shrugs
 *  at everything else, so a panel's own fetches cannot fail the test. */
function stubFetch(p: Progress = progress()) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url =
        typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const body = /\/progress$/.test(url) ? p : /\/projects\/1$/.test(url) ? PROJECT : [];
      return Promise.resolve(
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }),
  );
}

// Enough of the client for the header and for the two panels these tests
// render. Sections are exercised one at a time on purpose: this file is about
// the navigation, and each panel has its own tests for its own data.
const client = {
  getProgress: vi.fn(),
  listBatches: vi.fn().mockResolvedValue([]),
  listUnits: vi.fn().mockResolvedValue([]),
  myAnnotator: vi.fn().mockResolvedValue({ id: 9 }),
} as never;

const getProgress = () =>
  (client as unknown as { getProgress: ReturnType<typeof vi.fn> }).getProgress;

beforeEach(() => {
  window.localStorage.clear();
  window.localStorage.setItem("mlp.apiKey", "k");
  window.location.hash = "#/admin";
  mockViewport(1440);
});

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
  // @ts-expect-error — putting jsdom back the way we found it.
  delete window.matchMedia;
});

// --- the secondary rail -----------------------------------------------------

describe("the project sections", () => {
  /** Renders, then waits for the header fetch to land. Awaiting it is not
   *  incidental tidiness: the sections themselves are static, but leaving the
   *  progress promise in flight resolves it after the test ends, which React
   *  reports as an un-acted update and which makes the whole file noisy. */
  async function renderView(tab: Parameters<typeof ProjectView>[0]["tab"] = "progress") {
    getProgress().mockResolvedValue(progress());
    const result = render(<ProjectView client={client} projectId={1} apiKey="k" tab={tab} />);
    await screen.findByText(/units finalized/);
    return result;
  }

  it("groups the sections into named navigation landmarks", async () => {
    await renderView();

    // The grouping is the point of phase 3, and a grouping that exists only in
    // the pixels is not a grouping for everyone.
    for (const group of PROJECT_TAB_GROUPS) {
      const nav = screen.getByRole("navigation", { name: group.heading });
      const links = within(nav).getAllByRole("link");
      expect(links.map((l) => l.textContent)).toEqual(group.items.map((i) => i.label));
    }
  });

  it("makes every section a link to its own route", async () => {
    await renderView();

    expect(screen.getByTestId("tab-units")).toHaveAttribute("href", "#/admin/project/1/units");
    expect(screen.getByTestId("tab-export")).toHaveAttribute("href", "#/admin/project/1/export");
  });

  it("marks the current section with aria-current, and only that one", async () => {
    await renderView("units");

    expect(screen.getByTestId("tab-units")).toHaveAttribute("aria-current", "page");
    expect(screen.getByTestId("tab-progress")).not.toHaveAttribute("aria-current");
    expect(screen.getByTestId("tab-export")).not.toHaveAttribute("aria-current");
  });

  it("names the panel region after the current section", async () => {
    await renderView("units");
    // The `<h2>` is what stops the panels' `<h3>`s from hanging under nothing.
    expect(screen.getByRole("region", { name: "Units" })).toBeInTheDocument();
  });
});

// --- the header status line -------------------------------------------------

describe("the project header", () => {
  it("states where the project stands and how far along it is", async () => {
    getProgress().mockResolvedValue(progress());
    // Progress rather than Units: the header is what these tests are about, and
    // the unit browser's own fetch would settle after the assertions and be
    // reported as an un-acted update.
    render(<ProjectView client={client} projectId={1} apiKey="k" tab="progress" />);

    // Scoped to the header: "In progress" is also a funnel stat inside the
    // Progress panel, and a bare text query would happily match either. The
    // container exists during the load too, so wait on its contents, not on it.
    await waitFor(() =>
      expect(within(screen.getByTestId("project-status")).getByText("In progress")).toBeInTheDocument(),
    );
    // 1104 / 1842 — the completion the Progress tab used to keep to itself.
    expect(
      within(screen.getByTestId("project-status")).getByText(
        /1104 of 1842 units finalized \(59\.9%\)/,
      ),
    ).toBeInTheDocument();
  });

  it("surfaces escalations, which are the thing an admin has to act on", async () => {
    getProgress().mockResolvedValue(progress({ escalated: 6 }));
    // Progress rather than Units: the header is what these tests are about, and
    // the unit browser's own fetch would settle after the assertions and be
    // reported as an un-acted update.
    render(<ProjectView client={client} projectId={1} apiKey="k" tab="progress" />);

    expect(await screen.findByText("6 escalated")).toBeInTheDocument();
  });

  it("keeps the sections usable when the summary fails to load", async () => {
    getProgress().mockRejectedValue(new Error("503 upstream"));
    // Progress rather than Units: the header is what these tests are about, and
    // the unit browser's own fetch would settle after the assertions and be
    // reported as an un-acted update.
    render(<ProjectView client={client} projectId={1} apiKey="k" tab="progress" />);

    expect(await screen.findByText(/Project summary unavailable/)).toBeInTheDocument();
    // A failed header is not a failed page: navigation still works.
    expect(screen.getByTestId("tab-export")).toBeInTheDocument();
  });
});

// --- the route --------------------------------------------------------------

describe("the section in the URL", () => {
  it("opens the section named in the hash, and names the project in the h1", async () => {
    stubFetch();
    window.location.hash = "#/admin/project/1/units";
    render(<AdminApp />);

    // `findByRole` alone resolves on the *first* `<h1>`, which is still the
    // "Project #1" fallback shown while the name is in flight — so this has to
    // wait for the content, not merely for the element.
    await waitFor(() =>
      // "Project #1" told an admin nothing they could not read off the URL.
      expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(PROJECT.name),
    );
    await waitFor(() =>
      expect(screen.getByTestId("tab-units")).toHaveAttribute("aria-current", "page"),
    );
  });

  it("falls back to the id while the project name is still loading", async () => {
    // The fallback is deliberate: an empty heading during the fetch would be
    // worse than a dull one, and a project that 404s never gets a name at all.
    stubFetch();
    window.location.hash = "#/admin/project/1/export";
    render(<AdminApp />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Project #1");
    // Let the in-flight fetches land before the test ends, so their state
    // updates are not reported against whatever runs next.
    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(PROJECT.name),
    );
  });

  it("puts the section at the end of the breadcrumb", async () => {
    stubFetch();
    window.location.hash = "#/admin/project/1/export";
    render(<AdminApp />);

    await waitFor(() => {
      const crumbs = within(screen.getByRole("navigation", { name: "Breadcrumb" })).getAllByRole(
        "listitem",
      );
      expect(crumbs.map((c) => c.textContent)).toEqual(["Projects", PROJECT.name, "Export"]);
    });
    const crumbs = within(screen.getByRole("navigation", { name: "Breadcrumb" })).getAllByRole(
      "listitem",
    );
    // The project crumb is a link back to its default section; the last is not.
    expect(within(crumbs[1]).getByRole("link")).toHaveAttribute(
      "href",
      "#/admin/project/1/progress",
    );
    expect(within(crumbs[2]).getByText("Export")).toHaveAttribute("aria-current", "page");
  });

  it("ignores a project id that is not a number", async () => {
    stubFetch();
    window.location.hash = "#/admin/project/abc";
    render(<AdminApp />);

    // A NaN id used to reach the project screen and fetch `/projects/NaN`.
    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Projects"),
    );
  });

  it("survives a refresh, which component state did not", async () => {
    stubFetch();
    window.location.hash = "#/admin/project/1/export";
    const { unmount } = render(<AdminApp />);
    await waitFor(() =>
      expect(screen.getByTestId("tab-export")).toHaveAttribute("aria-current", "page"),
    );

    // A remount at the same URL is what a browser refresh looks like from here.
    // Before phase 3 this landed back on Progress every time.
    unmount();
    render(<AdminApp />);
    await waitFor(() =>
      expect(screen.getByTestId("tab-export")).toHaveAttribute("aria-current", "page"),
    );
  });

  it("follows a hash change without a remount", async () => {
    stubFetch();
    window.location.hash = "#/admin/project/1/units";
    render(<AdminApp />);
    await waitFor(() =>
      expect(screen.getByTestId("tab-units")).toHaveAttribute("aria-current", "page"),
    );

    window.location.hash = "#/admin/project/1/export";
    await waitFor(() =>
      expect(screen.getByTestId("tab-export")).toHaveAttribute("aria-current", "page"),
    );
    expect(screen.getByTestId("tab-units")).not.toHaveAttribute("aria-current");
  });

  it("lands an unknown section on the default rather than on nothing", async () => {
    stubFetch();
    window.location.hash = "#/admin/project/1/nonsense";
    render(<AdminApp />);

    await waitFor(() =>
      expect(screen.getByTestId("tab-progress")).toHaveAttribute("aria-current", "page"),
    );
  });

  it("announces the section and the project through the document title", async () => {
    stubFetch();
    window.location.hash = "#/admin/project/1/units";
    render(<AdminApp />);

    await waitFor(() =>
      expect(document.title).toBe(`Units · ${PROJECT.name} · Admin · MiniLP`),
    );
  });
});

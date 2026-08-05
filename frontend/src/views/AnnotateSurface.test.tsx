// The labeler surface (§ UX plan, phase 4).
//
// Annotate.test.tsx covers what the view *does* — selecting, canonicalizing,
// submitting. This file covers what the view *is*: the mode it declares, the
// document it forms, the things it announces, and where the controls live. Those
// were the phase-4 change, and they are the parts that regress silently, because
// nothing about a missing `aria-current` or a submit button that drifted back
// into the header shows up in a screenshot review.

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TaskClient } from "../api/client";
import type { Task, TemplateSchema } from "../api/types";
import { IMAGE_CLASSIFICATION, TEXT_SENTIMENT } from "../fixtures/gallery";
import { Annotate } from "./Annotate";

beforeEach(() => {
  try {
    window.localStorage.clear();
  } catch {
    /* no storage in this environment */
  }
});

const TASK: Task = {
  slot_id: 42,
  unit_id: 7,
  project_id: 1,
  payload: { image_url: "https://example.com/cat.jpg", context: "a small pet" },
  variant: null,
};

function mockClient(): TaskClient & { skip: ReturnType<typeof vi.fn> } {
  return {
    nextTask: vi.fn().mockResolvedValue(TASK),
    submit: vi.fn().mockResolvedValue({
      id: 1,
      slot_id: 42,
      unit_id: 7,
      annotator_id: 1,
      value: {},
      is_valid: true,
    }),
    skip: vi.fn().mockResolvedValue({ slot_id: 42, status: "open" }),
  };
}

function renderSurface(
  overrides: Partial<Parameters<typeof Annotate>[0]> = {},
  schema: TemplateSchema = IMAGE_CLASSIFICATION,
) {
  const client = overrides.client ?? mockClient();
  render(
    <Annotate
      client={client}
      annotatorId={1}
      projectId={1}
      schema={schema}
      projectName="Image QA · furniture catalogue"
      guidelines="# Judge the photo, not the product"
      {...overrides}
    />,
  );
  return client as ReturnType<typeof mockClient>;
}

// --- mode identity ----------------------------------------------------------

describe("labeler surface — mode identity", () => {
  it("declares the label mode, which is what re-points the accent to teal", async () => {
    renderSurface();
    const root = await screen.findByTestId("annotate-root");
    expect(root).toHaveAttribute("data-mode", "label");
  });

  it("keeps mode and theme independent so the two compose", async () => {
    renderSurface();
    const root = await screen.findByTestId("annotate-root");
    fireEvent.keyDown(window, { key: "d" });
    await waitFor(() => expect(root).toHaveAttribute("data-theme", "dark"));
    // Dark labeling is still labeling.
    expect(root).toHaveAttribute("data-mode", "label");
  });

  it("names the mode in words, because hue alone fails under deuteranopia", async () => {
    renderSurface();
    expect(await screen.findByTestId("mode-chip")).toHaveTextContent("Labeling");
  });

  it("announces the surface through the document title", async () => {
    renderSurface();
    await screen.findByTestId("input-rail");
    expect(document.title).toBe("Image QA · furniture catalogue · Labeling · MiniLP");
  });
});

// --- document structure -----------------------------------------------------

describe("labeler surface — document structure", () => {
  it("names the screen with an h1: the project, not the template", async () => {
    renderSurface();
    const h1 = await screen.findByRole("heading", { level: 1 });
    expect(h1).toHaveTextContent("Image QA · furniture catalogue");
  });

  it("falls back to the template name when no project name is supplied", async () => {
    renderSurface({ projectName: undefined });
    const h1 = await screen.findByRole("heading", { level: 1 });
    expect(h1).toHaveTextContent(IMAGE_CLASSIFICATION.name);
  });

  it("puts the skip link first in the tab order and lands it on <main>", async () => {
    const user = userEvent.setup();
    renderSurface();
    await screen.findByTestId("input-rail");

    await user.tab();
    const skip = screen.getByTestId("skip-link");
    expect(document.activeElement).toBe(skip);

    await user.click(skip);
    expect(document.activeElement).toBe(document.getElementById("main"));
  });

  it("renders the guidelines as a labelled complementary landmark", async () => {
    renderSurface();
    const aside = await screen.findByTestId("guidelines");
    expect(aside.tagName.toLowerCase()).toBe("aside");
    // Named, so "complementary" is not the only thing a landmark list has to
    // go on.
    expect(aside).toHaveAccessibleName("Guidelines");
  });

  it("drops page-level chrome when embedded in another page", async () => {
    // The template gallery and the visual builder both mount this view inside
    // the admin surface's own `<main>`. A second `<h1>`, a second `id="main"`
    // and a second skip link there would be a worse document than the one that
    // existed before this phase.
    const before = document.title;
    renderSurface({ embedded: true });
    await screen.findByTestId("input-rail");

    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
    expect(screen.queryByRole("main")).toBeNull();
    expect(screen.queryByTestId("skip-link")).toBeNull();
    expect(document.title).toBe(before);

    // The mode still reads as labeling — a preview of the labeler surface
    // should look like the labeler surface.
    expect(screen.getByTestId("annotate-root")).toHaveAttribute("data-mode", "label");
    expect(screen.getByTestId("taskbar")).toBeInTheDocument();
  });

  it("demotes headings inside author-written guidelines so the outline holds", async () => {
    // Guidelines reasonably start at `#`. Rendered as-is that is a second
    // `<h1>` competing with the one that names the screen.
    renderSurface({ guidelines: "# Judge the photo\n\nSome text." });
    const body = await screen.findByTestId("guidelines-body");
    expect(body.querySelector("h1")).toBeNull();
    expect(body.querySelector("h3")).toHaveTextContent("Judge the photo");
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });

  it("wires the guidelines toggle to the body it actually controls", async () => {
    renderSurface();
    const toggle = await screen.findByTestId("guidelines-toggle");
    const body = screen.getByTestId("guidelines-body");

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle.getAttribute("aria-controls")).toBe(body.id);
    expect(body).toBeVisible();

    await userEvent.setup().click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    // Still controlled by the same node — hidden, not removed.
    expect(toggle.getAttribute("aria-controls")).toBe(body.id);
    expect(body).not.toBeVisible();
  });
});

// --- session readouts -------------------------------------------------------

describe("labeler surface — session readouts", () => {
  it("reports progress as a value and as a sentence", async () => {
    renderSurface({ sessionGoal: 10 });
    await screen.findByTestId("input-category");
    const bar = screen.getByTestId("session-progress");

    expect(bar).toHaveAttribute("role", "progressbar");
    expect(bar).toHaveAttribute("aria-valuemax", "10");
    expect(bar).toHaveAttribute("aria-valuenow", "0");
    expect(bar).toHaveAttribute("aria-valuetext", "0 of 10 labeled this session");

    fireEvent.keyDown(window, { key: "1" });
    fireEvent.keyDown(window, { key: "Enter" });
    await waitFor(() =>
      expect(bar).toHaveAttribute("aria-valuetext", "1 of 10 labeled this session"),
    );
  });

  it("lights the first segment on the first label rather than rounding it away", async () => {
    renderSurface({ sessionGoal: 10 });
    await screen.findByTestId("input-category");
    const bar = screen.getByTestId("session-progress");
    expect(bar.querySelectorAll(".mlp-seg-on")).toHaveLength(0);

    fireEvent.keyDown(window, { key: "1" });
    fireEvent.keyDown(window, { key: "Enter" });
    await waitFor(() => expect(bar.querySelectorAll(".mlp-seg-on")).toHaveLength(1));
  });

  it("caps the segment count without lying about the numbers", async () => {
    renderSurface({ sessionGoal: 200 });
    const bar = await screen.findByTestId("session-progress");
    // The graphic approximates; the value does not.
    expect(bar.querySelectorAll(".mlp-seg").length).toBeLessThanOrEqual(24);
    expect(bar).toHaveAttribute("aria-valuemax", "200");
  });

  it("makes the session totals a polite live region", async () => {
    renderSurface();
    const stats = await screen.findByTestId("session-stats");
    expect(stats).toHaveAttribute("role", "status");
    expect(stats).toHaveAttribute("aria-live", "polite");
  });

  it("keeps the per-hour rate out of the live region", async () => {
    // The rate moves with the wall clock, so it changes on renders where
    // nothing happened — inside a live region that is a re-announcement of the
    // whole bar every time someone types a character.
    renderSurface();
    expect(await screen.findByTestId("stat-rate")).toHaveAttribute("aria-hidden", "true");
  });
});

// --- where the controls live ------------------------------------------------

describe("labeler surface — task bar and rail footer", () => {
  it("keeps unit actions out of the task bar", async () => {
    renderSurface();
    const bar = await screen.findByTestId("taskbar");
    expect(within(bar).queryByTestId("btn-submit")).toBeNull();
    expect(within(bar).queryByTestId("btn-skip")).toBeNull();
    expect(within(bar).queryByTestId("toggle-autosubmit")).toBeNull();
  });

  it("groups submit, skip and auto-submit in the rail footer", async () => {
    renderSurface();
    const footer = await screen.findByTestId("rail-footer");
    expect(within(footer).getByTestId("btn-submit")).toBeInTheDocument();
    expect(within(footer).getByTestId("btn-skip")).toBeInTheDocument();
    expect(within(footer).getByTestId("toggle-autosubmit")).toBeInTheDocument();
  });

  it("puts the footer inside the input rail, where the answer is", async () => {
    renderSurface();
    const rail = await screen.findByTestId("input-rail");
    expect(within(rail).getByTestId("rail-footer")).toBeInTheDocument();
  });

  it("hands the template's split ratio to the stylesheet instead of overriding it", async () => {
    // An inline `grid-template-columns` outranks every stylesheet rule, media
    // queries included, so the narrow-window fold could never fire. The ratio
    // has to be data the stylesheet reads.
    renderSurface(); // IMAGE_CLASSIFICATION is a 3:2 split
    await screen.findByTestId("input-rail");
    const grid = document.querySelector<HTMLElement>(".mlp-layout-split");
    expect(grid?.style.getPropertyValue("--grid-ratio")).toBe("3fr 2fr");
    expect(grid?.style.gridTemplateColumns).toBe("");
  });

  it("still submits from the footer button", async () => {
    const client = renderSurface();
    await screen.findByTestId("input-category");
    fireEvent.keyDown(window, { key: "1" });
    await userEvent.setup().click(screen.getByTestId("btn-submit"));
    await waitFor(() => expect(client.submit).toHaveBeenCalledTimes(1));
  });
});

// --- loading ----------------------------------------------------------------

describe("labeler surface — between tasks", () => {
  it("announces the load instead of swapping in a silent skeleton", async () => {
    // A never-resolving fetch holds the view in its loading state.
    const client: TaskClient = {
      nextTask: () => new Promise(() => {}),
      submit: vi.fn(),
      skip: vi.fn(),
    };
    renderSurface({ client });
    const loading = await screen.findByTestId("loading");
    expect(loading).toHaveAttribute("role", "status");
    expect(loading).toHaveTextContent("Loading the next task…");
  });
});

// --- the shortcuts dialog ---------------------------------------------------

describe("labeler surface — shortcuts dialog", () => {
  it("is a real modal dialog with an accessible name", async () => {
    const user = userEvent.setup();
    renderSurface();
    await screen.findByTestId("input-category");

    await user.click(screen.getByTestId("btn-help"));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleName("Keyboard shortcuts");
  });

  it("moves focus into the dialog and restores it to the trigger on close", async () => {
    const user = userEvent.setup();
    renderSurface();
    await screen.findByTestId("input-category");

    const trigger = screen.getByTestId("btn-help");
    await user.click(trigger);
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toBe(trigger);
  });

  it("closes from its own close button, not only from the scrim", async () => {
    const user = userEvent.setup();
    renderSurface();
    await screen.findByTestId("input-category");

    await user.click(screen.getByTestId("btn-help"));
    await user.click(await screen.findByTestId("overlay-close"));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("groups the shortcuts by the field they belong to", async () => {
    const user = userEvent.setup();
    renderSurface({}, TEXT_SENTIMENT);
    await screen.findByTestId("input-sentiment");

    await user.click(screen.getByTestId("btn-help"));
    const groups = await screen.findAllByTestId("overlay-group");
    const titles = groups.map((g) => g.querySelector("h3")?.textContent);
    expect(titles).toContain("Overall sentiment");
    // Reserved keys are a group of their own, and they come last: they are the
    // same on every template, so they are the part you already know.
    expect(titles[titles.length - 1]).toBe("Actions");
  });

  it("does not let hotkeys fire behind the dialog", async () => {
    const user = userEvent.setup();
    const client = renderSurface();
    await screen.findByTestId("input-category");

    await user.click(screen.getByTestId("btn-help"));
    await screen.findByRole("dialog");

    // 's' would skip the unit and 'x' would quit the project — both from a
    // keyboard the person is using to read a dialog.
    fireEvent.keyDown(window, { key: "s" });
    fireEvent.keyDown(window, { key: "x" });
    expect(client.skip).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    // '?' still closes it, because a toggle you cannot toggle back is a trap.
    fireEvent.keyDown(window, { key: "?" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});

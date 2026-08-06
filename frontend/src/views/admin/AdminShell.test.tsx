// Admin shell tests (§ UX plan, phase 2 + the accessibility baseline).
//
// These assert the properties the plan makes claims about, rather than the
// markup that happens to implement them: collapse persists, the mode is named,
// `aria-current` follows the route, the skip link actually moves focus, and the
// mobile drawer traps focus and gives it back. A snapshot test would pass while
// every one of those was broken.

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Command } from "../../components/CommandPalette";
import { AdminApp } from "./AdminApp";
import { AdminShell, COLLAPSE_STORAGE } from "./AdminShell";

const client = {
  myAnnotator: vi.fn().mockResolvedValue({ id: 9 }),
  listProjects: vi.fn().mockResolvedValue([]),
  listTemplates: vi.fn().mockResolvedValue([]),
} as never;

const paletteRun = vi.fn();
/** What the palette is filled with here is `commands.ts`'s business; the shell
 *  only has to open it, close it, and hand focus back. */
const PALETTE_COMMANDS: Command[] = [
  { id: "go:projects", group: "Go to", label: "Projects", run: paletteRun },
  { id: "go:templates", group: "Go to", label: "Templates", run: paletteRun },
];

/** jsdom has no `matchMedia`. Give it one that answers `max-width` honestly. */
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

function renderShell(over: Partial<Parameters<typeof AdminShell>[0]> = {}) {
  const props = {
    client,
    apiKey: "k",
    onApiKeyChange: vi.fn(),
    theme: "light" as const,
    onThemeChange: vi.fn(),
    active: "projects" as const,
    title: "Projects",
    crumbs: [],
    commands: PALETTE_COMMANDS,
    children: <p>body</p>,
    ...over,
  };
  return { ...render(<AdminShell {...props} />), props };
}

beforeEach(() => {
  window.localStorage.clear();
  window.location.hash = "#/admin";
  mockViewport(1440);
});

afterEach(() => {
  vi.clearAllMocks();
  // @ts-expect-error — putting jsdom back the way we found it.
  delete window.matchMedia;
});

// --- mode identity ----------------------------------------------------------

describe("mode identity", () => {
  it("marks the surface as admin mode and names it in words", () => {
    renderShell();

    expect(screen.getByTestId("admin-shell")).toHaveAttribute("data-mode", "admin");
    // The hue is reinforcement; the chip is the signal that survives a colour
    // vision deficiency, so it has to be text.
    expect(screen.getByTestId("mode-chip")).toHaveTextContent("Admin");
  });

  it("announces the mode through the document title", () => {
    renderShell({ title: "Templates" });
    expect(document.title).toBe("Templates · Admin · MiniLP");
  });
});

// --- rail: current item and collapse ---------------------------------------

describe("rail", () => {
  it("marks the active destination with aria-current, and only that one", () => {
    renderShell({ active: "templates" });

    expect(screen.getByTestId("rail-templates")).toHaveAttribute("aria-current", "page");
    expect(screen.getByTestId("rail-projects")).not.toHaveAttribute("aria-current");
    expect(screen.getByTestId("rail-marketplace")).not.toHaveAttribute("aria-current");
  });

  it("persists the collapsed state and restores it on the next visit", () => {
    const { unmount } = renderShell();
    const toggle = screen.getByTestId("rail-toggle");

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByTestId("admin-shell")).toHaveAttribute("data-collapsed", "true");
    expect(window.localStorage.getItem(COLLAPSE_STORAGE)).toBe("true");

    unmount();
    renderShell();

    expect(screen.getByTestId("rail-toggle")).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByTestId("admin-shell")).toHaveAttribute("data-collapsed", "true");
  });

  it("points the collapse toggle at the rail it controls", () => {
    renderShell();
    const controls = screen.getByTestId("rail-toggle").getAttribute("aria-controls");
    expect(controls).toBeTruthy();
    expect(screen.getByTestId("rail")).toHaveAttribute("id", controls!);
  });

  it("auto-collapses below 900px without overwriting the stored preference", () => {
    mockViewport(800);
    renderShell();

    expect(screen.getByTestId("admin-shell")).toHaveAttribute("data-collapsed", "true");
    // The admin never asked for this, so nothing should be remembered as if
    // they had — widening the window must give the labels back.
    expect(window.localStorage.getItem(COLLAPSE_STORAGE)).toBe("false");
  });

  it("lets the toggle expand a rail that auto-collapsed", () => {
    // Auto-collapse is a default, not an override. If the viewport wins
    // unconditionally, the toggle below 900px looks operable and does nothing.
    mockViewport(800);
    renderShell();
    expect(screen.getByTestId("admin-shell")).toHaveAttribute("data-collapsed", "true");

    fireEvent.click(screen.getByTestId("rail-toggle"));

    expect(screen.getByTestId("admin-shell")).toHaveAttribute("data-collapsed", "false");
  });

  it("names the toggle after what pressing it does", () => {
    renderShell();
    const toggle = screen.getByTestId("rail-toggle");

    expect(toggle).toHaveAccessibleName("Collapse");
    fireEvent.click(toggle);
    expect(toggle).toHaveAccessibleName("Expand");
  });

  it("hides icons from assistive technology so nothing is announced twice", () => {
    renderShell();
    const item = screen.getByTestId("rail-projects");

    // The label carries the name; the icon must contribute nothing, or the
    // item announces "Projects Projects".
    expect(item).toHaveAccessibleName("Projects");

    const svgs = item.querySelectorAll("svg");
    expect(svgs.length).toBeGreaterThan(0);
    svgs.forEach((svg) => {
      expect(svg).toHaveAttribute("aria-hidden", "true");
      expect(svg).toHaveAttribute("focusable", "false");
    });
  });
});

// --- skip link --------------------------------------------------------------

describe("skip link", () => {
  it("is the first tab stop on the page", () => {
    const { container } = renderShell();
    const focusables = container.querySelectorAll<HTMLElement>(
      "a[href], button:not([disabled]), input:not([disabled])",
    );
    expect(focusables[0]).toHaveAttribute("data-testid", "skip-link");
  });

  it("moves focus to <main> instead of navigating the hash router", () => {
    renderShell();
    fireEvent.click(screen.getByTestId("skip-link"));

    expect(document.activeElement).toBe(document.getElementById("main"));
    // The app routes on the hash: an unprevented "#main" would be parsed as a
    // route and land the admin in the annotation view.
    expect(window.location.hash).toBe("#/admin");
  });
});

// --- hotkeys ----------------------------------------------------------------

describe("hotkeys", () => {
  it("toggles the rail with [", () => {
    renderShell();
    fireEvent.keyDown(window, { key: "[" });
    expect(screen.getByTestId("admin-shell")).toHaveAttribute("data-collapsed", "true");

    fireEvent.keyDown(window, { key: "[" });
    expect(screen.getByTestId("admin-shell")).toHaveAttribute("data-collapsed", "false");
  });

  it("jumps with the g prefix", () => {
    renderShell();
    fireEvent.keyDown(window, { key: "g" });
    fireEvent.keyDown(window, { key: "t" });
    expect(window.location.hash).toBe("#/admin/templates");
  });

  it("does not fire while the caret is in a text field", () => {
    renderShell();
    const input = document.createElement("input");
    input.type = "text";
    document.body.appendChild(input);

    fireEvent.keyDown(input, { key: "[" });

    expect(screen.getByTestId("admin-shell")).toHaveAttribute("data-collapsed", "false");
    input.remove();
  });

  it("does not fire while a dialog is open", async () => {
    mockViewport(500);
    renderShell();
    fireEvent.click(screen.getByTestId("drawer-open"));
    await screen.findByTestId("rail-drawer");

    fireEvent.keyDown(window, { key: "g" });
    fireEvent.keyDown(window, { key: "t" });

    // Still where we started: a hotkey that navigates behind an open dialog
    // moves the page out from under it.
    expect(window.location.hash).toBe("#/admin");
  });
});

// --- command palette --------------------------------------------------------
//
// The widget's own contract is tested in components/CommandPalette.test.tsx.
// What belongs here is the wiring: the hotkey, the trigger, and the two things
// an open dialog owes the rest of the shell — focus on the way out, and silence
// from every other hotkey while it is up.

describe("command palette", () => {
  it("opens on Cmd+K and on Ctrl+K, and closes on the same key", async () => {
    renderShell();
    expect(screen.queryByTestId("command-palette")).not.toBeInTheDocument();

    fireEvent.keyDown(window, { key: "k", metaKey: true });
    await screen.findByTestId("command-palette");

    fireEvent.keyDown(window, { key: "k", metaKey: true });
    await waitFor(() =>
      expect(screen.queryByTestId("command-palette")).not.toBeInTheDocument(),
    );

    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    await screen.findByTestId("command-palette");
  });

  it("opens while the caret is in a text field", async () => {
    // The reason the palette hotkey is a modifier combination and the rail's
    // are bare letters: this is exactly where `[` and `g` cannot fire.
    renderShell();
    const input = document.createElement("input");
    input.type = "text";
    document.body.appendChild(input);
    input.focus();

    fireEvent.keyDown(input, { key: "k", metaKey: true });

    await screen.findByTestId("command-palette");
    input.remove();
  });

  it("opens from the command bar and reports its state", async () => {
    renderShell();
    const trigger = screen.getByTestId("palette-open");

    expect(trigger).toHaveAttribute("aria-haspopup", "dialog");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    // The visible text is the accessible name — a speech user saying "click
    // search or jump to" has to hit the thing they can read (WCAG 2.5.3).
    expect(trigger).toHaveAccessibleName(/Search or jump to/);

    fireEvent.click(trigger);

    await screen.findByTestId("command-palette");
    expect(screen.getByTestId("palette-open")).toHaveAttribute("aria-expanded", "true");
  });

  it("returns focus to the trigger even when opened from the keyboard", async () => {
    renderShell();
    // Nothing focused: without the shell focusing its own trigger first, the
    // trap would have nothing to restore to and Escape would drop the admin at
    // the top of the document.
    (document.activeElement as HTMLElement | null)?.blur();

    fireEvent.keyDown(window, { key: "k", metaKey: true });
    await screen.findByTestId("command-palette");

    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() =>
      expect(screen.queryByTestId("command-palette")).not.toBeInTheDocument(),
    );
    expect(document.activeElement).toBe(screen.getByTestId("palette-open"));
  });

  it("closes rather than reopens when the trigger is pressed again", async () => {
    // The scrim covers the trigger, so a real browser sends the press there and
    // swallows the click. jsdom does not, which makes this the worst case: if
    // the handler is a blind `open`, the palette shuts and immediately reopens.
    renderShell();
    fireEvent.click(screen.getByTestId("palette-open"));
    await screen.findByTestId("command-palette");

    fireEvent.click(screen.getByTestId("palette-open"));

    await waitFor(() =>
      expect(screen.queryByTestId("command-palette")).not.toBeInTheDocument(),
    );
  });

  it("tells the caller it opened, so the project list can be fetched lazily", async () => {
    const onPaletteOpen = vi.fn();
    renderShell({ onPaletteOpen });

    expect(onPaletteOpen).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("palette-open"));
    await screen.findByTestId("command-palette");

    expect(onPaletteOpen).toHaveBeenCalledTimes(1);
  });

  it("silences the rail hotkeys while it is open", async () => {
    renderShell();
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    await screen.findByTestId("command-palette");

    // Typing "g" then "t" into the palette must search for "gt", not navigate
    // the page out from under the dialog.
    fireEvent.keyDown(window, { key: "g" });
    fireEvent.keyDown(window, { key: "t" });
    fireEvent.keyDown(window, { key: "[" });

    expect(window.location.hash).toBe("#/admin");
    expect(screen.getByTestId("admin-shell")).toHaveAttribute("data-collapsed", "false");
  });

  it("runs a command from the shell's list", async () => {
    renderShell();
    fireEvent.click(screen.getByTestId("palette-open"));
    await screen.findByTestId("command-palette");

    fireEvent.keyDown(screen.getByTestId("palette-input"), { key: "Enter" });

    expect(paletteRun).toHaveBeenCalled();
  });
});

// --- mobile drawer ----------------------------------------------------------

describe("mobile drawer", () => {
  beforeEach(() => mockViewport(500));

  it("opens from the command bar and reports its state", async () => {
    renderShell();
    const opener = screen.getByTestId("drawer-open");

    expect(opener).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("rail-drawer")).not.toBeInTheDocument();

    fireEvent.click(opener);

    const drawer = await screen.findByTestId("rail-drawer");
    expect(drawer).toHaveAttribute("role", "dialog");
    expect(drawer).toHaveAttribute("aria-modal", "true");
    expect(drawer).toHaveAccessibleName("Navigation");
    expect(screen.getByTestId("drawer-open")).toHaveAttribute("aria-expanded", "true");
  });

  it("moves focus into the drawer and keeps Tab inside it", async () => {
    renderShell();
    fireEvent.click(screen.getByTestId("drawer-open"));
    const drawer = await screen.findByTestId("rail-drawer");

    await waitFor(() => expect(drawer.contains(document.activeElement)).toBe(true));

    const items = Array.from(
      drawer.querySelectorAll<HTMLElement>("a[href], button:not([disabled])"),
    );
    const first = items[0];
    const last = items[items.length - 1];

    last.focus();
    fireEvent.keyDown(last, { key: "Tab" });
    expect(document.activeElement).toBe(first);

    fireEvent.keyDown(first, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(last);
  });

  it("closes on Escape and gives focus back to the control that opened it", async () => {
    renderShell();
    const opener = screen.getByTestId("drawer-open");
    opener.focus();
    fireEvent.click(opener);
    await screen.findByTestId("rail-drawer");

    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => expect(screen.queryByTestId("rail-drawer")).not.toBeInTheDocument());
    expect(document.activeElement).toBe(screen.getByTestId("drawer-open"));
  });

  it("closes when a destination is chosen", async () => {
    renderShell();
    fireEvent.click(screen.getByTestId("drawer-open"));
    const drawer = await screen.findByTestId("rail-drawer");

    fireEvent.click(within(drawer).getByTestId("rail-templates"));

    await waitFor(() => expect(screen.queryByTestId("rail-drawer")).not.toBeInTheDocument());
  });
});

// --- API key popover --------------------------------------------------------

describe("API key popover", () => {
  it("keeps the key out of the header until asked for, with a real label", async () => {
    renderShell();
    const toggle = screen.getByTestId("api-key-toggle");

    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByLabelText("Admin API key")).not.toBeInTheDocument();

    fireEvent.click(toggle);

    const input = await screen.findByLabelText("Admin API key");
    expect(input).toHaveAttribute("type", "password");
    expect(input).toHaveAccessibleDescription(/Stored in this browser/);
    await waitFor(() => expect(document.activeElement).toBe(input));
  });

  it("closes on Escape and restores focus to its trigger", async () => {
    renderShell();
    const toggle = screen.getByTestId("api-key-toggle");
    fireEvent.click(toggle);
    await screen.findByTestId("api-key-popover");

    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => expect(screen.queryByTestId("api-key-popover")).not.toBeInTheDocument());
    expect(document.activeElement).toBe(toggle);
  });
});

// --- route → chrome ---------------------------------------------------------

describe("route resolution", () => {
  beforeEach(() => {
    window.localStorage.setItem("mlp.apiKey", "k");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } }),
      ),
    );
  });

  afterEach(() => vi.unstubAllGlobals());

  it("gives each screen one h1 and a breadcrumb ending in that screen", async () => {
    window.location.hash = "#/admin/new";
    render(<AdminApp />);

    const headings = await screen.findAllByRole("heading", { level: 1 });
    expect(headings).toHaveLength(1);
    expect(headings[0]).toHaveTextContent("New project");

    const crumbs = within(screen.getByRole("navigation", { name: "Breadcrumb" })).getAllByRole(
      "listitem",
    );
    expect(crumbs.map((c) => c.textContent)).toEqual(["Projects", "New project"]);
    expect(within(crumbs[1]).getByText("New project")).toHaveAttribute("aria-current", "page");
    // The parent crumb is a link back; the current one is not.
    expect(within(crumbs[0]).getByRole("link")).toHaveAttribute("href", "#/admin");
  });

  it("follows the route with aria-current on the rail", async () => {
    window.location.hash = "#/admin/marketplace";
    render(<AdminApp />);

    await waitFor(() =>
      expect(screen.getByTestId("rail-marketplace")).toHaveAttribute("aria-current", "page"),
    );
    expect(screen.getByTestId("rail-projects")).not.toHaveAttribute("aria-current");
  });
});

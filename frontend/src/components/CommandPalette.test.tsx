// Command palette tests (§ UX plan, phase 6).
//
// The plan says this phase "does not merge without a screen-reader pass", and
// the reason is that a combobox is one of the few widgets where the visible
// behaviour can be perfect while the announced behaviour is unusable. So these
// assert the ARIA contract as directly as the keyboard one: what
// `aria-activedescendant` points at, whether `aria-expanded` is telling the
// truth, and what the live region says — not just which command ran.

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { CommandPalette, filterCommands, groupCommands, type Command } from "./CommandPalette";

function cmd(over: Partial<Command> & { id: string; label: string }): Command {
  return { group: "Go to", run: () => {}, ...over };
}

const COMMANDS: Command[] = [
  cmd({ id: "go:projects", label: "Projects", hint: "Dashboard" }),
  cmd({ id: "go:templates", label: "Templates", hint: "Gallery" }),
  cmd({
    id: "section:units",
    label: "Units",
    group: "This project",
    hint: "Image QA · Monitor",
    keywords: "browser rows",
  }),
  cmd({
    id: "section:export",
    label: "Export",
    group: "This project",
    hint: "Image QA · Manage",
  }),
  cmd({ id: "action:new-project", label: "New project", group: "Actions", hint: "Wizard" }),
];

/** The palette as it is actually used: opened from a trigger, so focus has
 *  somewhere real to be restored to. */
function Harness({ commands = COMMANDS }: { commands?: Command[] }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button data-testid="trigger" onClick={() => setOpen(true)}>
        Search
      </button>
      {open && <CommandPalette commands={commands} onClose={() => setOpen(false)} />}
    </>
  );
}

async function openPalette(commands?: Command[]) {
  render(<Harness commands={commands} />);
  const trigger = screen.getByTestId("trigger");
  trigger.focus();
  fireEvent.click(trigger);
  const input = await screen.findByTestId("palette-input");
  await waitFor(() => expect(document.activeElement).toBe(input));
  return { trigger, input };
}

function type(input: HTMLElement, value: string) {
  fireEvent.change(input, { target: { value } });
}

/** What the combobox currently says is selected, by label. */
function activeLabel(input: HTMLElement): string | null {
  const id = input.getAttribute("aria-activedescendant");
  return id ? (document.getElementById(id)?.textContent ?? null) : null;
}

/* ==========================================================================
   Matching
   ========================================================================== */

describe("filterCommands", () => {
  const ids = (query: string) => filterCommands(COMMANDS, query).map((c) => c.id);

  it("leaves an empty query in the caller's order", () => {
    expect(filterCommands(COMMANDS, "   ")).toEqual(COMMANDS);
  });

  it("ranks a label prefix above a mid-word hit above a hint-only hit", () => {
    const ranked = filterCommands(
      [
        cmd({ id: "hint", label: "Roster", hint: "project people" }),
        cmd({ id: "mid", label: "New project" }),
        cmd({ id: "prefix", label: "Projects" }),
      ],
      "project",
    ).map((c) => c.id);

    // "New project" is a *word*-start hit, so it outranks nothing here except
    // the hint; the point is that all three match and the order is by quality.
    expect(ranked).toEqual(["prefix", "mid", "hint"]);
  });

  it("requires every token to match, so typing more always narrows", () => {
    expect(ids("image manage")).toEqual(["section:export"]);
    expect(ids("image nothing-like-this")).toEqual([]);
  });

  it("matches an initialism as a subsequence", () => {
    // What people type at a palette without being told they can.
    expect(ids("np")).toEqual(["action:new-project"]);
  });

  it("matches keywords that are never displayed", () => {
    expect(ids("rows")).toEqual(["section:units"]);
  });

  it("ignores case on both sides", () => {
    expect(ids("PROJECTS")).toContain("go:projects");
  });
});

describe("groupCommands", () => {
  it("keeps each group contiguous", () => {
    const groups = groupCommands([
      cmd({ id: "a", label: "Alpha", group: "First" }),
      cmd({ id: "b", label: "Beta", group: "Second" }),
      cmd({ id: "c", label: "Gamma", group: "First" }),
    ]);

    expect(groups.map((g) => g.heading)).toEqual(["First", "Second"]);
    // Ranking would otherwise interleave them, and a heading over a
    // non-contiguous run of options is a lie.
    expect(groups[0].items.map((c) => c.id)).toEqual(["a", "c"]);
  });

  it("lets a group lead when it holds the better match", () => {
    // "New project" (Actions) beats the two "This project" entries, which only
    // match through their group name — so Actions moves ahead of it, even
    // though it is last in the source list.
    const groups = groupCommands(filterCommands(COMMANDS, "pro"));
    expect(groups.map((g) => g.heading)).toEqual(["Go to", "Actions", "This project"]);
  });
});

/* ==========================================================================
   The widget
   ========================================================================== */

describe("the combobox contract", () => {
  it("is a combobox that owns the listbox and points at the first option", async () => {
    const { input } = await openPalette();

    expect(input).toHaveAttribute("role", "combobox");
    expect(input).toHaveAttribute("aria-expanded", "true");
    expect(input).toHaveAttribute("aria-autocomplete", "list");

    const listbox = screen.getByRole("listbox");
    expect(input.getAttribute("aria-controls")).toBe(listbox.getAttribute("id"));
    expect(activeLabel(input)).toContain("Projects");
  });

  it("groups the options and names each group once", async () => {
    await openPalette();

    const groups = screen.getAllByRole("group");
    expect(groups.map((g) => g.getAttribute("aria-label"))).toEqual([
      "Go to",
      "This project",
      "Actions",
    ]);
    // The visible heading is hidden from the reader, which hears the group's
    // name on entry instead — otherwise every option is prefixed by it.
    expect(within(groups[0]).getByText("Go to")).toHaveAttribute("aria-hidden", "true");
  });

  it("says it is collapsed, and controls nothing, when there are no matches", async () => {
    const { input } = await openPalette();
    type(input, "zzzz");

    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(input).toHaveAttribute("aria-expanded", "false");
    // A dangling `aria-controls` is worse than none: it promises a listbox the
    // reader can move into and then does not deliver one.
    expect(input).not.toHaveAttribute("aria-controls");
    expect(input).not.toHaveAttribute("aria-activedescendant");
    expect(screen.getByTestId("palette-empty")).toBeInTheDocument();
  });

  it("announces the result count through a polite live region", async () => {
    const { input } = await openPalette();
    const status = screen.getByTestId("palette-status");

    expect(status).toHaveAttribute("role", "status");
    expect(status).toHaveTextContent("5 commands");

    type(input, "units");
    expect(status).toHaveTextContent("1 command");

    type(input, "zzzz");
    expect(status).toHaveTextContent("No commands match");
  });
});

describe("keyboard", () => {
  it("moves the selection with the arrows and wraps at both ends", async () => {
    const { input } = await openPalette();

    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(activeLabel(input)).toContain("Templates");

    fireEvent.keyDown(input, { key: "ArrowUp" });
    expect(activeLabel(input)).toContain("Projects");

    // Up from the first lands on the last: a Down key that stops responding at
    // a boundary the admin cannot see is a dead end.
    fireEvent.keyDown(input, { key: "ArrowUp" });
    expect(activeLabel(input)).toContain("New project");

    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(activeLabel(input)).toContain("Projects");
  });

  it("jumps to the ends with Home and End", async () => {
    const { input } = await openPalette();

    fireEvent.keyDown(input, { key: "End" });
    expect(activeLabel(input)).toContain("New project");

    fireEvent.keyDown(input, { key: "Home" });
    expect(activeLabel(input)).toContain("Projects");
  });

  it("keeps DOM focus in the field so typing never stops working", async () => {
    const { input } = await openPalette();

    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowDown" });

    // The selection moved; focus did not. That is the whole reason this is an
    // activedescendant widget rather than a roving-tabindex one.
    expect(document.activeElement).toBe(input);
    type(input, "new");
    expect(input).toHaveValue("new");
  });

  it("puts the selection back on the best match after every keystroke", async () => {
    const { input } = await openPalette();
    fireEvent.keyDown(input, { key: "End" });
    expect(activeLabel(input)).toContain("New project");

    type(input, "t");

    // Otherwise one more character silently changes which command Enter runs.
    const options = screen.getAllByTestId("palette-option");
    expect(options[0]).toHaveAttribute("aria-selected", "true");
  });

  it("runs the selected command on Enter and closes", async () => {
    const run = vi.fn();
    const { input, trigger } = await openPalette([
      cmd({ id: "a", label: "Alpha" }),
      cmd({ id: "b", label: "Beta", run }),
    ]);

    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(run).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(screen.queryByTestId("command-palette")).not.toBeInTheDocument(),
    );
    expect(document.activeElement).toBe(trigger);
  });

  it("does nothing on Enter when nothing matches", async () => {
    const run = vi.fn();
    const { input } = await openPalette([cmd({ id: "a", label: "Alpha", run })]);
    type(input, "zzzz");

    fireEvent.keyDown(input, { key: "Enter" });

    expect(run).not.toHaveBeenCalled();
    expect(screen.getByTestId("command-palette")).toBeInTheDocument();
  });

  it("closes on Escape and gives focus back to the trigger", async () => {
    const { trigger } = await openPalette();

    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() =>
      expect(screen.queryByTestId("command-palette")).not.toBeInTheDocument(),
    );
    // The plan's condition of merge: "done improperly it is a keyboard trap".
    expect(document.activeElement).toBe(trigger);
  });

  it("keeps Tab inside the dialog", async () => {
    const { input } = await openPalette();

    fireEvent.keyDown(input, { key: "Tab" });
    expect(document.activeElement).toBe(input);

    fireEvent.keyDown(input, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(input);
  });
});

describe("pointer", () => {
  it("runs a clicked option", async () => {
    const run = vi.fn();
    await openPalette([cmd({ id: "a", label: "Alpha", run })]);

    fireEvent.click(screen.getByTestId("palette-option"));

    expect(run).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(screen.queryByTestId("command-palette")).not.toBeInTheDocument(),
    );
  });

  it("dismisses on a press outside the dialog but not inside it", async () => {
    await openPalette();

    fireEvent.mouseDown(screen.getByRole("dialog"));
    expect(screen.getByTestId("command-palette")).toBeInTheDocument();

    fireEvent.mouseDown(screen.getByTestId("command-palette"));
    await waitFor(() =>
      expect(screen.queryByTestId("command-palette")).not.toBeInTheDocument(),
    );
  });
});

describe("the dialog itself", () => {
  it("is a modal dialog with a name", async () => {
    await openPalette();
    const dialog = screen.getByRole("dialog");

    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleName("Command palette");
  });
});

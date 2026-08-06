// The command palette (UX plan, phase 6).
//
// `Cmd/Ctrl+K` over the admin surface's two navigation levels. In an app where
// getting to the unit browser of project 3 means dashboard → project → section,
// a palette removes most navigation entirely for anyone who uses it daily.
//
// This file is the widget only: it takes a list of `Command`s and knows nothing
// about projects, templates or routes. What is *in* the list is assembled in
// `views/admin/commands.ts`, which is where the app's knowledge lives.
//
// The plan is blunt about the risk — "done improperly it is a keyboard trap" —
// so the ARIA contract is the specification here, not a finishing touch. It is
// the APG combobox-with-listbox pattern:
//
//   • the text field is the `combobox`, and it is the only DOM focus point;
//     the "cursor" over the results is `aria-activedescendant`, not real focus,
//     so typing never stops working
//   • results are a `listbox` of `option`s grouped by `group`
//   • Up/Down move (wrapping), Home/End jump, Enter runs, Escape dismisses
//   • focus returns to whatever opened it (see `useFocusTrap`)
//   • a polite live region announces the result count as the query narrows
//
// `aria-expanded` is honest rather than decorative: with no matches there is no
// listbox in the DOM, so the combobox says it is collapsed and `aria-controls`
// is dropped rather than left pointing at nothing.

import { useEffect, useId, useMemo, useRef, useState } from "react";

import { IconEnter, IconSearch } from "./icons";
import { useFocusTrap } from "../hooks/useFocusTrap";

export interface Command {
  /** Stable across renders and unique in the list — it keys the option and its
   *  `aria-activedescendant` target. */
  id: string;
  label: string;
  /** The heading this command sits under. Also matched by the filter, so
   *  "template" finds everything in the Templates group. */
  group: string;
  /** Secondary line: where it goes, or what it will do. */
  hint?: string;
  /** Matched but never displayed — synonyms for what the label happens to call
   *  it ("annotators" for the roster, "csv" for export). */
  keywords?: string;
  run: () => void;
}

export interface CommandGroup {
  heading: string;
  items: Command[];
}

/* ==========================================================================
   Matching
   ========================================================================== */

// A word boundary for ranking purposes. Includes "·" because several labels in
// this app are built as "Project · section" and the part after the separator is
// a word an admin would reasonably type first.
const BOUNDARY = /[\s\-_/·:.]/;

/** Where `needle` sits in `hay`: 0 at the start, 1 at a word start, 2 inside a
 *  word, null if absent. Position is the whole of the ranking — a query that
 *  starts a label is a better answer than one that lands mid-word. */
function substringRank(hay: string, needle: string): number | null {
  const i = hay.indexOf(needle);
  if (i < 0) return null;
  if (i === 0) return 0;
  return BOUNDARY.test(hay[i - 1]) ? 1 : 2;
}

/** Are `needle`'s characters in `hay`, in order but not necessarily adjacent?
 *  This is what makes "np" find "New project" and "pu" find "Project · Units",
 *  which is the initialism people type at a palette without being told they
 *  can. */
function isSubsequence(hay: string, needle: string): boolean {
  let i = 0;
  for (const ch of hay) {
    if (ch === needle[i]) i += 1;
    if (i === needle.length) return true;
  }
  return needle.length === 0;
}

/** Cost of one token against one command, or null if it does not match. Lower
 *  is better; the tiers are deliberately far apart so a label hit always beats
 *  a hint hit no matter how many tokens are in play. */
function tokenCost(command: Command, token: string): number | null {
  const label = command.label.toLowerCase();
  const inLabel = substringRank(label, token);
  if (inLabel !== null) return inLabel;

  const rest = [command.hint, command.keywords, command.group]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  if (rest && substringRank(rest, token) !== null) return 4;

  // Last resort, and last on purpose: a subsequence match is the loosest thing
  // here and would otherwise bury exact hits under coincidences.
  if (isSubsequence(label, token)) return 8;
  return null;
}

/**
 * Rank `commands` against `query`. Every whitespace-separated token has to
 * match something, so typing more always narrows and never widens — the one
 * property people rely on without knowing they do.
 *
 * An empty query returns the list untouched, in the order the caller built it,
 * which is the order a person browsing rather than searching wants.
 */
export function filterCommands(commands: Command[], query: string): Command[] {
  const tokens = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (tokens.length === 0) return commands;

  const hits: { command: Command; cost: number; order: number }[] = [];
  commands.forEach((command, order) => {
    let cost = 0;
    for (const token of tokens) {
      const c = tokenCost(command, token);
      if (c === null) return; // one miss disqualifies the command
      cost += c;
    }
    hits.push({ command, cost, order });
  });

  hits.sort((a, b) => a.cost - b.cost || a.order - b.order);
  return hits.map((h) => h.command);
}

/** Bucket a ranked list by group, keeping both the order of the groups (by
 *  their best member) and the order within them. Headings only mean anything
 *  if the list under them is contiguous, and ranking would otherwise interleave
 *  them. */
export function groupCommands(commands: Command[]): CommandGroup[] {
  const groups: CommandGroup[] = [];
  const byHeading = new Map<string, CommandGroup>();
  for (const command of commands) {
    let group = byHeading.get(command.group);
    if (!group) {
      group = { heading: command.group, items: [] };
      byHeading.set(command.group, group);
      groups.push(group);
    }
    group.items.push(command);
  }
  return groups;
}

/* ==========================================================================
   The widget
   ========================================================================== */

export function CommandPalette({
  commands,
  onClose,
  placeholder = "Search projects, templates and actions…",
}: {
  commands: Command[];
  onClose: () => void;
  placeholder?: string;
}) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);

  const cardRef = useRef<HTMLDivElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const baseId = useId();
  const listId = `${baseId}-list`;
  const titleId = `${baseId}-title`;
  const optionId = (index: number) => `${baseId}-option-${index}`;

  const groups = useMemo(
    () => groupCommands(filterCommands(commands, query)),
    [commands, query],
  );
  // The flat list is the keyboard's model of the results, and it has to be in
  // exactly the order they are painted — hence derived from `groups` rather
  // than from the filter, which does not know about the grouping pass.
  const flat = useMemo(() => groups.flatMap((g) => g.items), [groups]);
  const indexOf = useMemo(
    () => new Map(flat.map((command, i) => [command.id, i])),
    [flat],
  );

  // Clamped rather than stored clamped: commands can arrive after the palette
  // is already open (the project list is fetched on first open), and a stale
  // index pointing past the end would leave Enter doing nothing at all.
  const activeIndex = flat.length === 0 ? -1 : Math.min(active, flat.length - 1);

  // Every keystroke puts the cursor back on the best match. Preserving the
  // position instead would mean typing one more character silently changes
  // which command Enter runs.
  useEffect(() => setActive(0), [query]);

  // A dialog the keyboard can walk out of, behind, and start operating the page
  // through is worse than no dialog. The hook also hands focus back to the
  // control that opened this, and closes on Escape.
  useFocusTrap(cardRef, true, onClose);

  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>('[aria-selected="true"]');
    // Optional-called: jsdom does no layout and has no `scrollIntoView`, and
    // the selection is the part that has to be correct anyway.
    el?.scrollIntoView?.({ block: "nearest" });
  }, [activeIndex]);

  const move = (delta: number) => {
    if (flat.length === 0) return;
    // Wrapping, because the alternative is a Down key that stops responding at
    // the bottom of a list whose bottom you cannot see.
    setActive((a) => (Math.min(a, flat.length - 1) + delta + flat.length) % flat.length);
  };

  const run = (command: Command) => {
    onClose();
    command.run();
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        move(1);
        break;
      case "ArrowUp":
        e.preventDefault();
        move(-1);
        break;
      case "Home":
        if (flat.length > 0) {
          e.preventDefault();
          setActive(0);
        }
        break;
      case "End":
        if (flat.length > 0) {
          e.preventDefault();
          setActive(flat.length - 1);
        }
        break;
      case "Enter": {
        const command = flat[activeIndex];
        if (command) {
          e.preventDefault();
          run(command);
        }
        break;
      }
      default:
        break;
    }
    // Escape is handled by the focus trap, which listens on the document in the
    // capture phase so it wins over anything that might swallow the key first.
  };

  const expanded = flat.length > 0;

  return (
    <div
      className="mlp-overlay mlp-palette-scrim"
      data-testid="command-palette"
      // `mousedown`, not `click`: a click that starts inside the palette and
      // ends on the scrim (a drag-select across the query field, which is a
      // thing people do) would otherwise dismiss it mid-gesture.
      onMouseDown={onClose}
    >
      <div
        className="mlp-palette"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        ref={cardRef}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <h2 id={titleId} className="mlp-visually-hidden">
          Command palette
        </h2>

        <div className="mlp-palette-field">
          <IconSearch size={18} className="mlp-palette-field-icon" />
          <input
            type="text"
            className="mlp-palette-input"
            data-testid="palette-input"
            role="combobox"
            aria-expanded={expanded}
            aria-controls={expanded ? listId : undefined}
            aria-activedescendant={activeIndex >= 0 ? optionId(activeIndex) : undefined}
            aria-autocomplete="list"
            aria-label="Search projects, templates and actions"
            autoComplete="off"
            spellCheck={false}
            placeholder={placeholder}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
          />
          <kbd className="mlp-badge" aria-hidden="true">
            esc
          </kbd>
        </div>

        <div className="mlp-palette-results" ref={listRef}>
          {expanded ? (
            <div
              role="listbox"
              id={listId}
              // Named separately from the dialog: a reader that has just been
              // told it is in the "Command palette" gains nothing from being
              // told the same thing again on entering the results.
              aria-label="Commands"
              className="mlp-palette-list"
            >
              {groups.map((group) => (
                <div
                  role="group"
                  // The heading is `aria-hidden` and the group is named here
                  // instead: a reader stepping through options should hear
                  // "Projects" once as it enters the group, not as part of
                  // every option's name.
                  aria-label={group.heading}
                  className="mlp-palette-group"
                  key={group.heading}
                >
                  <div className="mlp-palette-group-head" aria-hidden="true">
                    {group.heading}
                  </div>
                  {group.items.map((command) => {
                    const i = indexOf.get(command.id) ?? -1;
                    const isActive = i === activeIndex;
                    return (
                      <div
                        key={command.id}
                        id={optionId(i)}
                        role="option"
                        aria-selected={isActive}
                        className="mlp-palette-option"
                        data-testid="palette-option"
                        // `mousemove` rather than `mouseenter`: scrolling the
                        // list under a stationary pointer should not silently
                        // move the thing Enter is about to run.
                        onMouseMove={() => setActive(i)}
                        onClick={() => run(command)}
                      >
                        <span className="mlp-palette-option-label">{command.label}</span>
                        {command.hint && (
                          <span className="mlp-palette-option-hint">{command.hint}</span>
                        )}
                        {isActive && (
                          <IconEnter
                            size={14}
                            className="mlp-palette-option-enter"
                            data-testid="palette-active-marker"
                          />
                        )}
                      </div>
                    );
                  })}
                </div>
              ))}
            </div>
          ) : (
            <p className="mlp-palette-empty" data-testid="palette-empty">
              No commands match <strong>{query.trim()}</strong>.
            </p>
          )}
        </div>

        {/* Polite, and visually hidden because the count is already obvious to
            anyone who can see the list. Assertive would interrupt on every
            keystroke, which is the whole width of the difference. */}
        <p className="mlp-visually-hidden" role="status" data-testid="palette-status">
          {flat.length === 0
            ? "No commands match"
            : `${flat.length} command${flat.length === 1 ? "" : "s"}`}
        </p>

        <p className="mlp-palette-foot" aria-hidden="true">
          <kbd className="mlp-badge">↑</kbd>
          <kbd className="mlp-badge">↓</kbd> to move
          <span className="mlp-palette-foot-sep">·</span>
          <kbd className="mlp-badge">↵</kbd> to run
          <span className="mlp-palette-foot-sep">·</span>
          <kbd className="mlp-badge">esc</kbd> to close
        </p>
      </div>
    </div>
  );
}

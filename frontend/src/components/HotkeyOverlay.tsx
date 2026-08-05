import { useId, useRef } from "react";

import type { TemplateSchema } from "../api/types";
import { IconClose } from "./icons";
import { useFocusTrap } from "../hooks/useFocusTrap";
import { keyBadgeLabel, type HotkeyAssignment } from "../hotkeys/assign";
import { resolveOptions } from "../render/options";

export interface OverlayRow {
  key: string;
  label: string;
}

export interface OverlayGroup {
  title: string;
  rows: OverlayRow[];
}

/** Reserved keys, in the order a labeler needs them rather than alphabetically:
 *  the three that move work first, then the three that change the view. */
const ACTIONS: OverlayRow[] = [
  { key: "enter", label: "Submit" },
  { key: "s", label: "Skip" },
  { key: "u", label: "Undo last selection" },
  { key: "g", label: "Toggle guidelines" },
  { key: "d", label: "Toggle dark mode" },
  { key: "?", label: "Toggle this dialog" },
];

// Every interactive element with its key (§2.4 '?' overlay), grouped by the
// input it belongs to since phase 4. Built from the same assignment the badges
// use, so the dialog can never disagree with them.
//
// The grouping is not decoration: a flat list of nineteen rows makes the reader
// work out which "1" belongs to which question, and every row label had to
// repeat the field name to compensate. Under a heading it does not.
export function overlayGroups(
  schema: TemplateSchema,
  assignment: HotkeyAssignment,
): OverlayGroup[] {
  const groups: OverlayGroup[] = [];
  for (const input of schema.inputs) {
    const hk = assignment.byInput[input.id] ?? { options: {}, other: null };
    const rows: OverlayRow[] = [];
    for (const opt of resolveOptions(input, hk)) {
      if (opt.key) rows.push({ key: opt.key, label: opt.label });
    }
    if (hk.other) rows.push({ key: hk.other, label: "Other…" });
    // An input with no keys at all (free text, a slider) has nothing to say
    // here, and an empty heading is just noise.
    if (rows.length > 0) groups.push({ title: input.label || input.id, rows });
  }
  groups.push({ title: "Actions", rows: ACTIONS });
  return groups;
}

export function HotkeyOverlay({
  schema,
  assignment,
  onClose,
}: {
  schema: TemplateSchema;
  assignment: HotkeyAssignment;
  onClose: () => void;
}) {
  const groups = overlayGroups(schema, assignment);
  const cardRef = useRef<HTMLDivElement | null>(null);
  const titleId = useId();

  // A dialog that does not hold focus is one the keyboard can walk behind and
  // start answering the task through. The hook also restores focus to the help
  // button on close, which is the part people forget.
  useFocusTrap(cardRef, true, onClose);

  return (
    <div className="mlp-overlay" data-testid="hotkey-overlay" onClick={onClose}>
      <div
        className="mlp-overlay-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        ref={cardRef}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mlp-overlay-head">
          <h2 id={titleId}>Keyboard shortcuts</h2>
          <button
            type="button"
            className="mlp-icon-btn"
            onClick={onClose}
            data-testid="overlay-close"
          >
            <IconClose />
            <span className="mlp-visually-hidden">Close keyboard shortcuts</span>
          </button>
        </div>

        {groups.map((group) => (
          <section className="mlp-overlay-group" key={group.title} data-testid="overlay-group">
            <h3>{group.title}</h3>
            {group.rows.map((r, i) => (
              <div className="mlp-overlay-row" key={`${r.key}-${i}`} data-testid="overlay-row">
                <span>{r.label}</span>
                <kbd className="mlp-badge" data-hotkey={r.key}>
                  {keyBadgeLabel(r.key)}
                </kbd>
              </div>
            ))}
          </section>
        ))}

        <p className="mlp-muted mlp-overlay-foot">Press ? or Esc to close.</p>
      </div>
    </div>
  );
}

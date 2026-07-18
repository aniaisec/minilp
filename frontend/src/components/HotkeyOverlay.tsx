import type { TemplateSchema } from "../api/types";
import { keyBadgeLabel, type HotkeyAssignment } from "../hotkeys/assign";
import { resolveOptions } from "../render/options";

export interface OverlayRow {
  key: string;
  label: string;
}

// Every interactive element with its key (§2.4 '?' overlay). Built from the same
// assignment the badges use, so the overlay can never disagree with them.
export function overlayRows(schema: TemplateSchema, assignment: HotkeyAssignment): OverlayRow[] {
  const rows: OverlayRow[] = [];
  for (const input of schema.inputs) {
    const hk = assignment.byInput[input.id] ?? { options: {}, other: null };
    for (const opt of resolveOptions(input, hk)) {
      if (opt.key) rows.push({ key: opt.key, label: `${input.label || input.id}: ${opt.label}` });
    }
    if (hk.other) rows.push({ key: hk.other, label: `${input.label || input.id}: Other…` });
  }
  // Reserved actions (§2.4).
  rows.push({ key: "enter", label: "Submit" });
  rows.push({ key: "s", label: "Skip" });
  rows.push({ key: "g", label: "Toggle guidelines" });
  rows.push({ key: "d", label: "Toggle dark mode" });
  rows.push({ key: "u", label: "Undo last selection" });
  rows.push({ key: "?", label: "Toggle this overlay" });
  return rows;
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
  const rows = overlayRows(schema, assignment);
  return (
    <div className="mlp-overlay" data-testid="hotkey-overlay" onClick={onClose}>
      <div className="mlp-overlay-card" onClick={(e) => e.stopPropagation()}>
        <h3 style={{ marginTop: 0 }}>Keyboard shortcuts</h3>
        {rows.map((r, i) => (
          <div className="mlp-overlay-row" key={`${r.key}-${i}`} data-testid="overlay-row">
            <span>{r.label}</span>
            <kbd className="mlp-badge" data-hotkey={r.key}>
              {keyBadgeLabel(r.key)}
            </kbd>
          </div>
        ))}
        <p className="mlp-muted" style={{ marginBottom: 0 }}>
          Press ? or Esc to close.
        </p>
      </div>
    </div>
  );
}

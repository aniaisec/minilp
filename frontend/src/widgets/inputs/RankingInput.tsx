import { useId, useState } from "react";

import { moveInOrder, rankingOrder } from "../../render/options";
import type { InputWidgetProps } from "./types";

// Drag to order N options (§2.1 M6). Value shape: string[] — *ordered*, which is
// why a ranking key defaults to the `ordered` match rule rather than the
// set-comparison `exact` used for checkboxes (§6.4).
//
// Native HTML5 drag-and-drop, plus ↑/↓ buttons and Alt+↑/↓ on a focused row.
// The keyboard path is not a fallback: §12 M3 requires every task be completable
// without a mouse, and drag-and-drop with no non-drag alternative is a WCAG 2.2
// failure outright.
//
// Phase 4 adds the half that was missing. A move rearranged the list silently:
// a sighted user watches the row travel, a screen-reader user heard nothing, so
// there was no way to tell a successful move from a keystroke that never
// registered. Every move now writes a sentence into a polite live region naming
// the item and its new position, and the list carries its instructions through
// `aria-describedby` rather than leaving them in a paragraph that merely happens
// to sit underneath.
export function RankingInput({ input, value, onChange }: InputWidgetProps) {
  const [dragging, setDragging] = useState<number | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const uid = useId();
  const order = rankingOrder(input, value);

  const announce = (item: string, to: number, total: number) =>
    setAnnouncement(`${item} moved to position ${to + 1} of ${total}.`);

  const move = (from: number, delta: number) => {
    const next = moveInOrder(order, from, delta);
    if (next === order) return; // already at an end
    onChange(next);
    announce(order[from], from + delta, next.length);
  };

  const drop = (to: number) => {
    if (dragging === null || dragging === to) return;
    const next = [...order];
    const [item] = next.splice(dragging, 1);
    next.splice(to, 0, item);
    setDragging(null);
    onChange(next);
    announce(item, to, next.length);
  };

  return (
    <div className="mlp-field" data-testid={`input-${input.id}`}>
      <div className="mlp-field-label" id={`${uid}-label`}>
        {input.label}
        {input.required ? " *" : ""}
      </div>
      {input.help && <div className="mlp-field-help mlp-muted">{input.help}</div>}
      <ol
        className="mlp-ranking"
        data-testid={`${input.id}-ranking`}
        aria-labelledby={`${uid}-label`}
        aria-describedby={`${uid}-hint`}
      >
        {order.map((item, i) => (
          <li
            key={item}
            className={dragging === i ? "mlp-rank-row mlp-rank-dragging" : "mlp-rank-row"}
            draggable
            tabIndex={0}
            // The row says where it is: the visible position is a separate span
            // that the row's own accessible name would not otherwise include.
            aria-label={`${item}, position ${i + 1} of ${order.length}`}
            data-testid={`${input.id}-rank-${item}`}
            data-position={i + 1}
            onDragStart={() => setDragging(i)}
            onDragEnd={() => setDragging(null)}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              drop(i);
            }}
            onKeyDown={(e) => {
              if (!e.altKey) return;
              if (e.key === "ArrowUp") {
                e.preventDefault();
                move(i, -1);
              } else if (e.key === "ArrowDown") {
                e.preventDefault();
                move(i, 1);
              }
            }}
          >
            <span className="mlp-rank-num mlp-mono" aria-hidden="true">
              {i + 1}
            </span>
            <span className="mlp-rank-grip" aria-hidden="true">
              ⠿
            </span>
            <span className="mlp-rank-label">{item}</span>
            <span className="mlp-rank-actions">
              <button
                type="button"
                className="mlp-btn mlp-btn-tiny"
                aria-label={`Move ${item} up`}
                disabled={i === 0}
                data-testid={`${input.id}-up-${item}`}
                onClick={() => move(i, -1)}
              >
                <span aria-hidden="true">↑</span>
              </button>
              <button
                type="button"
                className="mlp-btn mlp-btn-tiny"
                aria-label={`Move ${item} down`}
                disabled={i === order.length - 1}
                data-testid={`${input.id}-down-${item}`}
                onClick={() => move(i, 1)}
              >
                <span aria-hidden="true">↓</span>
              </button>
            </span>
          </li>
        ))}
      </ol>
      {/* Keyboard paths first, drag last: the order the sentence is read in is
          the order the paths get discovered. */}
      <p className="mlp-muted mlp-field-hint" id={`${uid}-hint`}>
        Use the ↑/↓ buttons, focus a row and press Alt+↑ / Alt+↓, or drag a row.
      </p>
      {/* Polite, and off-screen: the move has already happened, so it can wait
          for a gap rather than interrupting. */}
      <span
        className="mlp-visually-hidden"
        role="status"
        aria-live="polite"
        data-testid={`${input.id}-rank-announcer`}
      >
        {announcement}
      </span>
    </div>
  );
}

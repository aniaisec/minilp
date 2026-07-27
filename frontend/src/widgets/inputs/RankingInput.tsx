import { useState } from "react";

import { moveInOrder, rankingOrder } from "../../render/options";
import type { InputWidgetProps } from "./types";

// Drag to order N options (§2.1 M6). Value shape: string[] — *ordered*, which is
// why a ranking key defaults to the `ordered` match rule rather than the
// set-comparison `exact` used for checkboxes (§6.4).
//
// Native HTML5 drag-and-drop, plus ↑/↓ buttons and Alt+↑/↓ on a focused row.
// The keyboard path is not a fallback: §12 M3 requires every task be completable
// without a mouse, and a drag is unusable with a keyboard alone.
export function RankingInput({ input, value, onChange }: InputWidgetProps) {
  const [dragging, setDragging] = useState<number | null>(null);
  const order = rankingOrder(input, value);

  const move = (from: number, delta: number) => {
    const next = moveInOrder(order, from, delta);
    if (next !== order) onChange(next);
  };

  const drop = (to: number) => {
    if (dragging === null || dragging === to) return;
    const next = [...order];
    const [item] = next.splice(dragging, 1);
    next.splice(to, 0, item);
    setDragging(null);
    onChange(next);
  };

  return (
    <div className="mlp-field" data-testid={`input-${input.id}`}>
      <div className="mlp-field-label">
        {input.label}
        {input.required ? " *" : ""}
      </div>
      {input.help && <div className="mlp-field-help mlp-muted">{input.help}</div>}
      <ol className="mlp-ranking" data-testid={`${input.id}-ranking`}>
        {order.map((item, i) => (
          <li
            key={item}
            className={dragging === i ? "mlp-rank-row mlp-rank-dragging" : "mlp-rank-row"}
            draggable
            tabIndex={0}
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
            <span className="mlp-rank-num mlp-mono">{i + 1}</span>
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
                ↑
              </button>
              <button
                type="button"
                className="mlp-btn mlp-btn-tiny"
                aria-label={`Move ${item} down`}
                disabled={i === order.length - 1}
                data-testid={`${input.id}-down-${item}`}
                onClick={() => move(i, 1)}
              >
                ↓
              </button>
            </span>
          </li>
        ))}
      </ol>
      <p className="mlp-muted mlp-field-hint">
        Drag a row, use ↑/↓, or focus a row and press Alt+↑ / Alt+↓.
      </p>
    </div>
  );
}

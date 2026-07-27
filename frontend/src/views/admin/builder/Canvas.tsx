// The builder canvas: an ordered list you can drag into and reorder (§11).
//
// Native HTML5 drag-and-drop, no dependency — dropping a palette entry appends,
// dragging a row reorders. Every drag has a keyboard equivalent (Alt+↑/↓ on a
// focused row), because "drag to reorder" alone would make the builder the one
// surface in MiniLP you cannot drive from the keyboard.

import type { ReactNode } from "react";
import { useState } from "react";

export const PALETTE_MIME = "application/x-minilp-palette";

export interface CanvasItem {
  key: string;
  title: ReactNode;
  type: string;
}

export function Canvas({
  items,
  selected,
  emptyHint,
  onSelect,
  onReorder,
  onDropNew,
  onRemove,
  testId,
}: {
  items: CanvasItem[];
  selected: number | null;
  emptyHint: string;
  onSelect: (index: number) => void;
  onReorder: (from: number, to: number) => void;
  onDropNew: (type: string) => void;
  onRemove: (index: number) => void;
  testId: string;
}) {
  const [dragging, setDragging] = useState<number | null>(null);
  const [over, setOver] = useState(false);

  // A drop either carries a palette type (add) or a row index (reorder).
  const handleDrop = (e: React.DragEvent, index: number | null) => {
    e.preventDefault();
    setOver(false);
    const paletteType = e.dataTransfer.getData(PALETTE_MIME);
    if (paletteType) {
      onDropNew(paletteType);
    } else if (dragging !== null && index !== null) {
      onReorder(dragging, index);
    }
    setDragging(null);
  };

  return (
    <div
      className={over ? "mlp-canvas mlp-canvas-over" : "mlp-canvas"}
      data-testid={testId}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => handleDrop(e, null)}
    >
      {items.length === 0 && <div className="mlp-canvas-empty">{emptyHint}</div>}
      {items.map((item, i) => (
        <div
          key={item.key}
          className={
            i === selected
              ? "mlp-canvas-item mlp-canvas-item-selected"
              : "mlp-canvas-item"
          }
          data-testid={`${testId}-item-${i}`}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.stopPropagation();
            handleDrop(e, i);
          }}
        >
          <div
            className="mlp-canvas-head"
            draggable
            role="button"
            tabIndex={0}
            aria-label={`${item.type} at position ${i + 1}`}
            data-position={i + 1}
            data-testid={`${testId}-head-${i}`}
            onDragStart={() => setDragging(i)}
            onDragEnd={() => setDragging(null)}
            onClick={() => onSelect(i)}
            onKeyDown={(e) => {
              if (e.altKey && e.key === "ArrowUp") {
                e.preventDefault();
                onReorder(i, i - 1);
              } else if (e.altKey && e.key === "ArrowDown") {
                e.preventDefault();
                onReorder(i, i + 1);
              } else if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onSelect(i);
              }
            }}
          >
            <span aria-hidden="true">⠿</span>
            <span className="mlp-canvas-title">{item.title}</span>
            <span className="mlp-canvas-type">{item.type}</span>
            <button
              type="button"
              className="mlp-btn mlp-btn-tiny"
              aria-label={`Move up: ${item.type}`}
              disabled={i === 0}
              data-testid={`${testId}-up-${i}`}
              onClick={(e) => {
                e.stopPropagation();
                onReorder(i, i - 1);
              }}
            >
              ↑
            </button>
            <button
              type="button"
              className="mlp-btn mlp-btn-tiny"
              aria-label={`Move down: ${item.type}`}
              disabled={i === items.length - 1}
              data-testid={`${testId}-down-${i}`}
              onClick={(e) => {
                e.stopPropagation();
                onReorder(i, i + 1);
              }}
            >
              ↓
            </button>
            <button
              type="button"
              className="mlp-btn mlp-btn-tiny"
              aria-label={`Remove: ${item.type}`}
              data-testid={`${testId}-remove-${i}`}
              onClick={(e) => {
                e.stopPropagation();
                onRemove(i);
              }}
            >
              ✕
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

/** A palette entry: draggable onto the canvas, clickable as the keyboard path. */
export function PaletteButton({
  type,
  label,
  hint,
  onAdd,
}: {
  type: string;
  label: string;
  hint: string;
  onAdd: (type: string) => void;
}) {
  return (
    <button
      type="button"
      className="mlp-palette-item"
      draggable
      title={hint}
      data-testid={`palette-${type}`}
      onDragStart={(e) => {
        e.dataTransfer.setData(PALETTE_MIME, type);
        e.dataTransfer.effectAllowed = "copy";
      }}
      onClick={() => onAdd(type)}
    >
      {label}
      <span className="mlp-muted" style={{ display: "block", fontSize: 11 }}>
        {hint}
      </span>
    </button>
  );
}

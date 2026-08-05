import { useId } from "react";

import { Badge } from "../../components/Badge";
import { applyOption, resolveOptions } from "../../render/options";
import type { InputWidgetProps } from "./types";

// Star rating (§2.1 M6) — a likert skin, so it shares the scale config, the
// integer value shape, and the 1..N hotkeys. Stars fill up to the selection,
// which is the whole reason to pick this over a row of numbered buttons.
//
// Phase 4 fixes what the stars said out loud. Each button announced a bare
// "3 of 5", which is a position on a scale with no indication of what that
// position *means* — the word the scale attaches to it ("ok", "good") was in a
// `title`, which is the one place assistive technology is least likely to look.
// The accessible name now carries both, and the readout beside the stars is a
// polite live region so a change is heard without hunting for it.
export function RatingInput({ input, hotkeys, value, onChange }: InputWidgetProps) {
  const opts = resolveOptions(input, hotkeys);
  const current = typeof value === "number" ? value : null;
  const uid = useId();

  return (
    <div
      className="mlp-field"
      role="radiogroup"
      aria-labelledby={`${uid}-label`}
      data-testid={`input-${input.id}`}
    >
      <div className="mlp-field-label" id={`${uid}-label`}>
        {input.label}
        {input.required ? " *" : ""}
      </div>
      {input.help && <div className="mlp-field-help mlp-muted">{input.help}</div>}
      <div className="mlp-rating">
        {opts.map((opt) => {
          const n = Number(opt.raw);
          const filled = current !== null && n <= current;
          // "good — 4 of 5" rather than "4 of 5": the scale word is the reason
          // the rating exists, and the position alone makes the listener count.
          const name =
            opt.label && opt.label !== String(n)
              ? `${opt.label} — ${n} of ${opts.length}`
              : `${n} of ${opts.length}`;
          return (
            <button
              type="button"
              key={opt.label}
              className={filled ? "mlp-star mlp-star-on" : "mlp-star"}
              role="radio"
              aria-checked={current === n}
              aria-label={name}
              title={opt.label}
              data-testid={`${input.id}-opt-${n}`}
              onClick={() => onChange(applyOption(input, value, opt))}
            >
              <span aria-hidden="true">{filled ? "★" : "☆"}</span>
              <Badge hotkey={opt.key} />
            </button>
          );
        })}
        <span
          className="mlp-muted mlp-rating-readout"
          data-testid={`${input.id}-readout`}
          role="status"
          aria-live="polite"
        >
          {current === null ? "not rated" : `${current} / ${opts.length}`}
        </span>
      </div>
    </div>
  );
}

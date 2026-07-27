import { Badge } from "../../components/Badge";
import { applyOption, resolveOptions } from "../../render/options";
import type { InputWidgetProps } from "./types";

// Star rating (§2.1 M6) — a likert skin, so it shares the scale config, the
// integer value shape, and the 1..N hotkeys. Stars fill up to the selection,
// which is the whole reason to pick this over a row of numbered buttons.
export function RatingInput({ input, hotkeys, value, onChange }: InputWidgetProps) {
  const opts = resolveOptions(input, hotkeys);
  const current = typeof value === "number" ? value : null;

  return (
    <div
      className="mlp-field"
      role="radiogroup"
      aria-label={input.label}
      data-testid={`input-${input.id}`}
    >
      <div className="mlp-field-label">
        {input.label}
        {input.required ? " *" : ""}
      </div>
      {input.help && <div className="mlp-field-help mlp-muted">{input.help}</div>}
      <div className="mlp-rating">
        {opts.map((opt) => {
          const n = Number(opt.raw);
          const filled = current !== null && n <= current;
          return (
            <button
              type="button"
              key={opt.label}
              className={filled ? "mlp-star mlp-star-on" : "mlp-star"}
              role="radio"
              aria-checked={current === n}
              aria-label={`${n} of ${opts.length}`}
              title={opt.label}
              data-testid={`${input.id}-opt-${n}`}
              onClick={() => onChange(applyOption(input, value, opt))}
            >
              <span aria-hidden="true">{filled ? "★" : "☆"}</span>
              <Badge hotkey={opt.key} />
            </button>
          );
        })}
        <span className="mlp-muted mlp-rating-readout" data-testid={`${input.id}-readout`}>
          {current === null ? "not rated" : `${current} / ${opts.length}`}
        </span>
      </div>
    </div>
  );
}

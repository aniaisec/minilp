import { useId } from "react";

import type { InputWidgetProps } from "./types";

// Bounded numeric entry (§2.1 M6). Value shape: number.
// No hotkeys — it is a typing target, so digits must reach the box.
//
// Phase 4 gives the bounds a voice. `min`/`max` on the element are enforced by
// the browser's own validation, which a labeler never sees because this form is
// not submitted natively — so a value outside the range was accepted silently
// and rejected later, by the backend, on someone else's screen. The range hint
// and the out-of-range message are both associated by id, so the field reads as
// "Confidence, 0 … 10, 14 is outside the allowed range" rather than as a number
// box with some grey text under it.
export function NumberInput({ input, value, onChange }: InputWidgetProps) {
  const uid = useId();
  const bounded = input.min !== undefined || input.max !== undefined;

  const num = typeof value === "number" ? value : Number(value);
  const outOfRange =
    Number.isFinite(num) &&
    ((input.min !== undefined && num < input.min) ||
      (input.max !== undefined && num > input.max));

  const describedBy = [
    input.help ? `${uid}-help` : null,
    bounded ? `${uid}-range` : null,
    outOfRange ? `${uid}-err` : null,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="mlp-field" data-testid={`input-${input.id}`}>
      <label className="mlp-field-label" htmlFor={`num-${input.id}`}>
        {input.label}
        {input.required ? " *" : ""}
      </label>
      {input.help && (
        <div className="mlp-field-help mlp-muted" id={`${uid}-help`}>
          {input.help}
        </div>
      )}
      <input
        id={`num-${input.id}`}
        className={outOfRange ? "mlp-text mlp-number mlp-invalid" : "mlp-text mlp-number"}
        type="number"
        min={input.min}
        max={input.max}
        step={input.step}
        value={typeof value === "number" || typeof value === "string" ? String(value) : ""}
        aria-invalid={outOfRange || undefined}
        aria-describedby={describedBy || undefined}
        data-testid={`${input.id}-number`}
        onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))}
      />
      {bounded && (
        <span className="mlp-muted mlp-field-hint" id={`${uid}-range`}>
          {input.min ?? "−∞"} … {input.max ?? "∞"}
        </span>
      )}
      {outOfRange && (
        <p className="mlp-field-error" id={`${uid}-err`} data-testid={`${input.id}-error`}>
          Enter a value between {input.min ?? "−∞"} and {input.max ?? "∞"}.
        </p>
      )}
    </div>
  );
}

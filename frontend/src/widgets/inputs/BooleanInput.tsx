import { Badge } from "../../components/Badge";
import { applyOption, resolveOptions } from "../../render/options";
import type { InputWidgetProps } from "./types";

// Yes/no toggle (§2.1 M6). Value shape: bool.
//
// Rendered as two buttons rather than a checkbox on purpose: a checkbox has no
// way to distinguish "answered no" from "not answered", and `required` needs
// that distinction (§2.3).
export function BooleanInput({ input, hotkeys, value, onChange }: InputWidgetProps) {
  const opts = resolveOptions(input, hotkeys);
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
      <div className="mlp-choice-row">
        {opts.map((opt) => (
          <button
            type="button"
            key={opt.label}
            className={value === opt.raw ? "mlp-option mlp-option-selected" : "mlp-option"}
            role="radio"
            aria-checked={value === opt.raw}
            data-testid={`${input.id}-opt-${opt.label}`}
            onClick={() => onChange(applyOption(input, value, opt))}
          >
            <Badge hotkey={opt.key} />
            <span className="mlp-option-label">{opt.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

import { Badge } from "../../components/Badge";
import { applyOption, resolveOptions } from "../../render/options";
import type { InputWidgetProps } from "./types";

// Labeled scale (§2.1). Value shape: int (min + index). Keys 1..N (§2.4).
export function LikertInput({ input, hotkeys, value, onChange }: InputWidgetProps) {
  const opts = resolveOptions(input, hotkeys);
  return (
    <div className="mlp-field" role="radiogroup" aria-label={input.label} data-testid={`input-${input.id}`}>
      <div className="mlp-field-label">
        {input.label}
        {input.required ? " *" : ""}
      </div>
      <div className="mlp-choice-row">
        {opts.map((opt) => (
          <button
            type="button"
            key={opt.label}
            className="mlp-option"
            role="radio"
            aria-checked={value === opt.raw}
            data-testid={`${input.id}-opt-${opt.raw}`}
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

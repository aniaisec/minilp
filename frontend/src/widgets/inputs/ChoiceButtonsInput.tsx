import { Badge } from "../../components/Badge";
import { applyOption, resolveOptions } from "../../render/options";
import type { InputWidgetProps } from "./types";

// Large keyboard-mapped buttons, e.g. Left / Tie / Right (§2.1). Value shape:
// string (raw side). Canonicalization to the chosen item happens at submit (§2.7).
export function ChoiceButtonsInput({ input, hotkeys, value, onChange }: InputWidgetProps) {
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

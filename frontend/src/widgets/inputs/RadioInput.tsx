import { Badge } from "../../components/Badge";
import { applyOption, resolveOptions } from "../../render/options";
import { OtherEntry } from "./OtherEntry";
import type { InputWidgetProps } from "./types";

// Single-select radio (§2.1). Value shape: string. allow_other supported.
export function RadioInput(props: InputWidgetProps) {
  const { input, hotkeys, value, onChange } = props;
  const opts = resolveOptions(input, hotkeys);
  return (
    <div className="mlp-field" role="radiogroup" aria-label={input.label} data-testid={`input-${input.id}`}>
      <div className="mlp-field-label">
        {input.label}
        {input.required ? " *" : ""}
      </div>
      <div className="mlp-options-list">
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
        <OtherEntry {...props} />
      </div>
    </div>
  );
}

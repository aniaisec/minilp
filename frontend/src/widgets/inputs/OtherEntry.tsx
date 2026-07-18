import { applyOther, isOtherActive, otherText } from "../../render/options";
import { Badge } from "../../components/Badge";
import type { InputWidgetProps } from "./types";

// The "Other…" escape hatch shared by radio/checkbox (§2.1 allow_other, §2.4 key 'o').
export function OtherEntry({ input, hotkeys, value, onChange }: InputWidgetProps) {
  if (!input.allow_other) return null;
  const active = isOtherActive(input, value);
  return (
    <div className="mlp-option" aria-checked={active} role="radio" data-testid={`${input.id}-other`}>
      <Badge hotkey={hotkeys.other} />
      <span className="mlp-option-label">Other…</span>
      {active ? (
        <input
          className="mlp-text"
          autoFocus
          value={otherText(value)}
          placeholder="type a label"
          data-testid={`${input.id}-other-text`}
          onChange={(e) => onChange(applyOther(input, value, e.target.value))}
        />
      ) : null}
    </div>
  );
}

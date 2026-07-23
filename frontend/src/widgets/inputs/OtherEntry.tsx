import { applyOther, isOtherActive, otherText, toggleOther } from "../../render/options";
import { Badge } from "../../components/Badge";
import type { InputWidgetProps } from "./types";

// The "Other…" escape hatch shared by radio/checkbox (§2.1 allow_other, §2.4 key 'o').
// Clicking the row activates the free-text entry (and reveals its box); clicking
// again while empty clears it. The click handler is what was missing — before,
// "Other…" only responded to the 'o' hotkey, so a mouse user got no text box.
export function OtherEntry({ input, hotkeys, value, onChange }: InputWidgetProps) {
  if (!input.allow_other) return null;
  const active = isOtherActive(input, value);

  const activate = () => {
    // If it isn't active yet, turn it on (empty text) so the box appears and the
    // radio reads as selected; if it's already active, leave the text as typed.
    if (!active) onChange(toggleOther(input, value));
  };

  return (
    <div
      className={active ? "mlp-option mlp-option-selected" : "mlp-option"}
      aria-checked={active}
      role="radio"
      tabIndex={0}
      data-testid={`${input.id}-other`}
      onClick={activate}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          activate();
        }
      }}
    >
      <Badge hotkey={hotkeys.other} />
      <span className="mlp-option-label">Other…</span>
      {active ? (
        <input
          className="mlp-text"
          autoFocus
          value={otherText(value)}
          placeholder="type a label"
          data-testid={`${input.id}-other-text`}
          // Don't let a click inside the text box bubble up to the row handler.
          onClick={(e) => e.stopPropagation()}
          onChange={(e) => onChange(applyOther(input, value, e.target.value))}
        />
      ) : null}
    </div>
  );
}

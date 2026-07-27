import type { InputWidgetProps } from "./types";

// Bounded numeric entry (§2.1 M6). Value shape: number.
// No hotkeys — it is a typing target, so digits must reach the box.
export function NumberInput({ input, value, onChange }: InputWidgetProps) {
  return (
    <div className="mlp-field" data-testid={`input-${input.id}`}>
      <label className="mlp-field-label" htmlFor={`num-${input.id}`}>
        {input.label}
        {input.required ? " *" : ""}
      </label>
      {input.help && <div className="mlp-field-help mlp-muted">{input.help}</div>}
      <input
        id={`num-${input.id}`}
        className="mlp-text mlp-number"
        type="number"
        min={input.min}
        max={input.max}
        step={input.step}
        value={typeof value === "number" || typeof value === "string" ? String(value) : ""}
        data-testid={`${input.id}-number`}
        onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))}
      />
      {(input.min !== undefined || input.max !== undefined) && (
        <span className="mlp-muted mlp-field-hint">
          {input.min ?? "−∞"} … {input.max ?? "∞"}
        </span>
      )}
    </div>
  );
}

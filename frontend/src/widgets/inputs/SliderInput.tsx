import type { InputWidgetProps } from "./types";

// Continuous bounded scale (§2.1 M6). Value shape: number.
// The live read-out matters: a slider with no number is a guess, not a judgment.
export function SliderInput({ input, value, onChange }: InputWidgetProps) {
  const min = input.min ?? 0;
  const max = input.max ?? 1;
  const step = input.step ?? (max - min) / 100;
  const current = typeof value === "number" ? value : Number(value);
  const shown = Number.isFinite(current) ? current : min;

  return (
    <div className="mlp-field" data-testid={`input-${input.id}`}>
      <label className="mlp-field-label" htmlFor={`sl-${input.id}`}>
        {input.label}
        {input.required ? " *" : ""}
      </label>
      {input.help && <div className="mlp-field-help mlp-muted">{input.help}</div>}
      <div className="mlp-slider-row">
        <span className="mlp-muted mlp-mono">{min}</span>
        <input
          id={`sl-${input.id}`}
          className="mlp-slider"
          type="range"
          min={min}
          max={max}
          step={step}
          value={shown}
          data-testid={`${input.id}-slider`}
          onChange={(e) => onChange(Number(e.target.value))}
        />
        <span className="mlp-muted mlp-mono">{max}</span>
        <output className="mlp-slider-value mlp-mono" data-testid={`${input.id}-slider-value`}>
          {Number.isFinite(current) ? current : "—"}
        </output>
      </div>
    </div>
  );
}

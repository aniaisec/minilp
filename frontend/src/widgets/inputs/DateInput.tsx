import type { InputWidgetProps } from "./types";

// Date / datetime entry (§2.1 M6). Value shape: an ISO-8601 string
// ('YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM'), which is exactly what the native input
// produces — so no canonicalizer is needed and the stored value sorts correctly
// as a plain string.
export function DateInput({ input, value, onChange }: InputWidgetProps) {
  const withTime = input.type === "datetime";
  return (
    <div className="mlp-field" data-testid={`input-${input.id}`}>
      <label className="mlp-field-label" htmlFor={`date-${input.id}`}>
        {input.label}
        {input.required ? " *" : ""}
      </label>
      {input.help && <div className="mlp-field-help mlp-muted">{input.help}</div>}
      <input
        id={`date-${input.id}`}
        className="mlp-text"
        type={withTime ? "datetime-local" : "date"}
        value={typeof value === "string" ? value : ""}
        data-testid={`${input.id}-date`}
        onChange={(e) => onChange(e.target.value || undefined)}
      />
    </div>
  );
}

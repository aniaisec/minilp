import type { InputWidgetProps } from "./types";

// Free-text entry (§2.1). Value shape: string. No hotkeys (typing target).
export function FreeTextInput({ input, value, onChange }: InputWidgetProps) {
  return (
    <div className="mlp-field" data-testid={`input-${input.id}`}>
      <label className="mlp-field-label" htmlFor={`ft-${input.id}`}>
        {input.label}
        {input.required ? " *" : ""}
      </label>
      <textarea
        id={`ft-${input.id}`}
        className="mlp-textarea"
        rows={3}
        value={typeof value === "string" ? value : ""}
        data-testid={`${input.id}-text`}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

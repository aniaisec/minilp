import { useId, useState } from "react";

import type { InputWidgetProps } from "./types";

// Free-text entry (§2.1). Value shape: string. No hotkeys (typing target).
//
// Phase 4 wires up the two things a text field owes the keyboard: its help text
// is associated with `aria-describedby` instead of merely sitting nearby, and a
// required field left empty says so through a message tied to the input by id,
// with `aria-invalid` to match. The message waits for blur — telling someone a
// field is required before they have had a chance to fill it in is scolding,
// not helping.
export function FreeTextInput({ input, value, onChange }: InputWidgetProps) {
  const uid = useId();
  const [touched, setTouched] = useState(false);

  const text = typeof value === "string" ? value : "";
  const missing = Boolean(input.required) && touched && text.trim().length === 0;
  const describedBy = [input.help ? `${uid}-help` : null, missing ? `${uid}-err` : null]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="mlp-field" data-testid={`input-${input.id}`}>
      <label className="mlp-field-label" htmlFor={`ft-${input.id}`}>
        {input.label}
        {input.required ? " *" : ""}
      </label>
      {input.help && (
        <div className="mlp-field-help mlp-muted" id={`${uid}-help`}>
          {input.help}
        </div>
      )}
      <textarea
        id={`ft-${input.id}`}
        className={missing ? "mlp-textarea mlp-invalid" : "mlp-textarea"}
        rows={3}
        value={text}
        aria-invalid={missing || undefined}
        aria-describedby={describedBy || undefined}
        data-testid={`${input.id}-text`}
        onChange={(e) => onChange(e.target.value)}
        onBlur={() => setTouched(true)}
      />
      {missing && (
        <p className="mlp-field-error" id={`${uid}-err`} data-testid={`${input.id}-error`}>
          This answer is required.
        </p>
      )}
    </div>
  );
}

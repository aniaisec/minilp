import { useState } from "react";

import type { InputWidgetProps } from "./types";

// Free-form tag entry (§2.1 M6). Value shape: string[].
//
// Enter or comma commits a tag; Backspace on an empty box removes the last one.
// Canonicalization (trim / lower-case / de-duplicate) happens in `render/canonical`
// and again server-side — the widget keeps whatever the annotator typed as `raw`.
export function TagsInput({ input, value, onChange }: InputWidgetProps) {
  const [draft, setDraft] = useState("");
  const tags = Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];

  const commit = (text: string) => {
    const tag = text.trim();
    if (!tag) return;
    if (!tags.includes(tag)) onChange([...tags, tag]);
    setDraft("");
  };

  return (
    <div className="mlp-field" data-testid={`input-${input.id}`}>
      <label className="mlp-field-label" htmlFor={`tags-${input.id}`}>
        {input.label}
        {input.required ? " *" : ""}
      </label>
      {input.help && <div className="mlp-field-help mlp-muted">{input.help}</div>}
      <div className="mlp-chip-row">
        {tags.map((tag, i) => (
          <span key={`${tag}-${i}`} className="mlp-chip mlp-chip-on">
            {tag}
            <button
              type="button"
              className="mlp-chip-x"
              aria-label={`Remove ${tag}`}
              data-testid={`${input.id}-remove-${tag}`}
              onClick={() => onChange(tags.filter((_, j) => j !== i))}
            >
              ×
            </button>
          </span>
        ))}
      </div>
      <input
        id={`tags-${input.id}`}
        className="mlp-text"
        value={draft}
        placeholder="type a tag, press Enter"
        data-testid={`${input.id}-tag-entry`}
        onChange={(e) => {
          // A typed comma commits, so pasting "a, b, c" lands three tags.
          if (e.target.value.includes(",")) {
            const parts = e.target.value.split(",");
            parts.slice(0, -1).forEach(commit);
            setDraft(parts[parts.length - 1]);
          } else {
            setDraft(e.target.value);
          }
        }}
        onBlur={() => commit(draft)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            // Don't let Enter reach the global dispatcher and submit the task.
            e.preventDefault();
            e.stopPropagation();
            commit(draft);
          } else if (e.key === "Backspace" && draft === "" && tags.length) {
            onChange(tags.slice(0, -1));
          }
        }}
      />
    </div>
  );
}

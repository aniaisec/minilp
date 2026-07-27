import { applyOption, resolveOptions } from "../../render/options";
import { OtherEntry } from "./OtherEntry";
import type { InputWidgetProps } from "./types";

// Multi-select dropdown (§2.1 M6). Value shape: string[].
//
// A native multiple <select> rather than a pile of checkboxes: this type exists
// for lists long enough that checkboxes would sprawl past the fold. Toggling
// routes through `applyOption` so a click and a (future) key produce the same
// raw array.
export function MultiSelectInput(props: InputWidgetProps) {
  const { input, hotkeys, value, onChange } = props;
  const opts = resolveOptions(input, hotkeys);
  const selected = Array.isArray(value) ? value : [];

  return (
    <div className="mlp-field" data-testid={`input-${input.id}`}>
      <label className="mlp-field-label" htmlFor={`msel-${input.id}`}>
        {input.label}
        {input.required ? " *" : ""}
      </label>
      {input.help && <div className="mlp-field-help mlp-muted">{input.help}</div>}
      <select
        id={`msel-${input.id}`}
        className="mlp-select mlp-multiselect"
        multiple
        size={Math.min(opts.length, 8)}
        value={selected.filter((v): v is string => typeof v === "string")}
        data-testid={`${input.id}-multiselect`}
        onChange={(e) => {
          const picked = Array.from(e.target.selectedOptions, (o) => o.value);
          // Preserve any "other:…" entry the dropdown doesn't know about.
          const other = selected.filter(
            (v) => typeof v === "string" && v.startsWith("other:"),
          );
          onChange([...picked, ...other]);
        }}
      >
        {opts.map((opt) => (
          <option key={opt.label} value={String(opt.raw)}>
            {opt.label}
          </option>
        ))}
      </select>
      <div className="mlp-chip-row">
        {opts.map((opt) => {
          const on = selected.includes(opt.raw);
          return (
            <button
              type="button"
              key={opt.label}
              className={on ? "mlp-chip mlp-chip-on" : "mlp-chip"}
              aria-pressed={on}
              data-testid={`${input.id}-opt-${opt.label}`}
              onClick={() => onChange(applyOption(input, value, opt))}
            >
              {opt.label}
            </button>
          );
        })}
      </div>
      <OtherEntry {...props} />
    </div>
  );
}

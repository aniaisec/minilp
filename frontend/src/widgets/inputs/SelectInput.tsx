import { resolveOptions } from "../../render/options";
import { OtherEntry } from "./OtherEntry";
import type { InputWidgetProps } from "./types";

// Single-select dropdown (§2.1 M6). Value shape: string.
//
// The point of `select` over `radio` is a long option list: it gets no per-option
// hotkeys precisely because 40 options would exhaust the key budget (§2.4). The
// select element itself is keyboard-navigable, so the field is still reachable
// without a mouse.
export function SelectInput(props: InputWidgetProps) {
  const { input, hotkeys, value, onChange } = props;
  const opts = resolveOptions(input, hotkeys);
  const isOther = typeof value === "string" && value.startsWith("other:");

  return (
    <div className="mlp-field" data-testid={`input-${input.id}`}>
      <label className="mlp-field-label" htmlFor={`sel-${input.id}`}>
        {input.label}
        {input.required ? " *" : ""}
      </label>
      {input.help && <div className="mlp-field-help mlp-muted">{input.help}</div>}
      <select
        id={`sel-${input.id}`}
        className="mlp-select"
        value={isOther ? "" : typeof value === "string" ? value : ""}
        data-testid={`${input.id}-select`}
        onChange={(e) => onChange(e.target.value === "" ? undefined : e.target.value)}
      >
        <option value="">— choose —</option>
        {opts.map((opt) => (
          <option key={opt.label} value={String(opt.raw)}>
            {opt.label}
          </option>
        ))}
      </select>
      <OtherEntry {...props} />
    </div>
  );
}

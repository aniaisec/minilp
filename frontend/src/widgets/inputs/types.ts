import type { InputField } from "../../api/types";
import type { InputHotkeys } from "../../hotkeys/assign";

// Common props for every input widget (§2.6). Widgets are controlled: they render
// the current raw value and report changes; the central view owns the answer map
// and the keyboard dispatcher, so mouse and keyboard stay in lockstep.
export interface InputWidgetProps {
  input: InputField;
  hotkeys: InputHotkeys;
  value: unknown;
  onChange: (raw: unknown) => void;
}

export type { InputField, InputHotkeys };

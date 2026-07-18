import { keyBadgeLabel } from "../hotkeys/assign";

// A small key hint badge rendered on each interactive element (§2.4).
export function Badge({ hotkey }: { hotkey?: string | null }) {
  if (!hotkey) return null;
  return (
    <kbd className="mlp-badge" data-hotkey={hotkey}>
      {keyBadgeLabel(hotkey)}
    </kbd>
  );
}

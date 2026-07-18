// Map a browser KeyboardEvent to the normalized token space used by assign.ts.
// Keeps runtime dispatch and badge assignment on the same vocabulary.

export function eventToken(e: {
  key: string;
  shiftKey?: boolean;
}): string {
  const k = e.key;
  switch (k) {
    case "ArrowLeft":
      return "left";
    case "ArrowRight":
      return "right";
    case "ArrowUp":
      return "up";
    case "ArrowDown":
      return "down";
    case "Enter":
      return "enter";
    case "Escape":
      return "escape";
    case " ":
      return "space";
    default:
      // "?" arrives as "?" already (Shift+/). Single chars lowercased.
      return k.length === 1 ? k.toLowerCase() : k.toLowerCase();
  }
}

// Should this event be ignored because focus is in a text entry field?
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName.toLowerCase();
  if (tag === "input") {
    const t = (target as HTMLInputElement).type;
    return t === "text" || t === "search" || t === "url" || t === "email" || t === "";
  }
  return tag === "textarea" || target.isContentEditable;
}

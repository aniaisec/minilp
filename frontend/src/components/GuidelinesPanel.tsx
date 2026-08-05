import { useId } from "react";

import { IconBook, IconChevronRight } from "./icons";
import { renderMarkdown } from "../render/markdown";

// Annotator instructions (§1.7, §11) — a collapsible drawer since phase 4.
//
// It used to be a card in the flow: permanently expanded, competing with the
// task for the top of the screen, and pushing the actual work below the fold on
// the first unit of every session. It is now an `<aside>` — complementary
// content, which is what guidelines are — that collapses to a single row.
//
// Open/closed state stays with the parent, because `g` toggles it from the
// view's keyboard dispatcher, and two sources of truth for one boolean is how
// the hotkey and the button end up disagreeing.
//
// The body is always rendered and hidden with the `hidden` attribute rather
// than removed. That keeps `aria-controls` pointing at something real in both
// states — a control claiming to control a node that does not exist is worse
// than no `aria-controls` at all.
export function GuidelinesPanel({
  markdown,
  open,
  onToggle,
}: {
  markdown: string;
  open: boolean;
  onToggle: () => void;
}) {
  const id = useId();
  if (!markdown) return null;
  return (
    <aside
      className="mlp-guidelines"
      // `aria-label` rather than `aria-labelledby` pointing at the heading: the
      // heading contains the toggle *and* its key badge, so the landmark would
      // otherwise be announced as "Guidelines G, complementary".
      aria-label="Guidelines"
      data-testid="guidelines"
      data-open={open ? "true" : "false"}
    >
      {/* An `<h2>`: the page `<h1>` is the project name in the task bar, and a
          landmark that a screen reader can jump to should say what it is. */}
      <h2 className="mlp-guidelines-head">
        <button
          type="button"
          className="mlp-guidelines-toggle"
          aria-expanded={open}
          aria-controls={`${id}-body`}
          onClick={onToggle}
          data-testid="guidelines-toggle"
        >
          <span className="mlp-guidelines-caret" aria-hidden="true">
            <IconChevronRight size={14} />
          </span>
          <span className="mlp-guidelines-icon" aria-hidden="true">
            <IconBook size={15} />
          </span>
          <span className="mlp-guidelines-label">Guidelines</span>
          <kbd className="mlp-badge" data-hotkey="g">
            G
          </kbd>
        </button>
      </h2>
      <div
        id={`${id}-body`}
        className="mlp-guidelines-body"
        hidden={!open}
        data-testid="guidelines-body"
        // Offset by two: the drawer's own heading is the `<h2>`, so guidelines
        // that sensibly start at `#` land at `<h3>` instead of colliding with
        // the page `<h1>`.
        dangerouslySetInnerHTML={{ __html: renderMarkdown(markdown, { headingOffset: 2 }) }}
      />
    </aside>
  );
}

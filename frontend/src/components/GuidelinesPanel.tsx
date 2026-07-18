import { renderMarkdown } from "../render/markdown";

// Collapsible annotator instructions (§1.7, §11): expanded on the first task,
// collapsed after; 'g' toggles. Controlled by the parent view.
export function GuidelinesPanel({
  markdown,
  open,
  onToggle,
}: {
  markdown: string;
  open: boolean;
  onToggle: () => void;
}) {
  if (!markdown) return null;
  return (
    <section className="mlp-card mlp-guidelines" data-testid="guidelines">
      <button
        type="button"
        className="mlp-btn"
        aria-expanded={open}
        onClick={onToggle}
        data-testid="guidelines-toggle"
        style={{ border: "none", background: "none", padding: 0, fontWeight: 600 }}
      >
        {open ? "▾" : "▸"} Guidelines <span className="mlp-muted">(g)</span>
      </button>
      {open ? (
        <div
          className="mlp-guidelines-body"
          data-testid="guidelines-body"
          dangerouslySetInnerHTML={{ __html: renderMarkdown(markdown) }}
        />
      ) : null}
    </section>
  );
}

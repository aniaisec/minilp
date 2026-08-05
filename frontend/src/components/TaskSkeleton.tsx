// The between-tasks state (§ UX plan, phase 4).
//
// A labeler sees this on every single unit, which is what makes it worth more
// than the word "Loading…" in a card. Two problems with the string: the page
// collapsed to one line and then jumped back to full height, and a screen
// reader was told nothing at all, because swapping text into the DOM is silent.
//
// So: a shape that occupies roughly the space the task will, and a `role="status"`
// region carrying the only sentence worth speaking. The blocks themselves are
// `aria-hidden` — announcing "grey rectangle" six times helps nobody.
//
// The shimmer is a CSS animation and therefore already covered by the global
// `prefers-reduced-motion` block in theme.css; it degrades to a flat tint.
export function TaskSkeleton({ split = true }: { split?: boolean }) {
  return (
    <div
      className={split ? "mlp-skeleton mlp-skeleton-split" : "mlp-skeleton"}
      role="status"
      data-testid="loading"
    >
      <span className="mlp-visually-hidden">Loading the next task…</span>
      <div className="mlp-card mlp-skel-display" aria-hidden="true">
        <div className="mlp-skel-block mlp-skel-media" />
      </div>
      <div className="mlp-card mlp-skel-rail" aria-hidden="true">
        <div className="mlp-skel-block mlp-skel-line-lg" />
        <div className="mlp-skel-block mlp-skel-row" />
        <div className="mlp-skel-block mlp-skel-row" />
        <div className="mlp-skel-block mlp-skel-row" />
        <div className="mlp-skel-block mlp-skel-line" />
      </div>
    </div>
  );
}

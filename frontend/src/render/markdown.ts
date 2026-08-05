// Minimal, safe markdown → HTML. Escapes first, then applies a small subset
// (headings, bold, italic, inline code, links, paragraphs, line breaks). Kept
// dependency-free and XSS-safe; the full renderer is a post-v1 concern.

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function inline(s: string): string {
  return s
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>")
    .replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, '<a href="$1" rel="noreferrer">$1</a>');
}

export interface MarkdownOptions {
  /**
   * Push every heading down by this many levels (§ UX plan, "headings descending
   * without skipping levels").
   *
   * Guidelines are author-written and reasonably start at `#`. Dropped into a
   * page unchanged, that `#` becomes a second `<h1>` competing with the one
   * that names the screen, and the document outline stops being navigable. The
   * caller knows how deep the content sits; the renderer does not, so it is a
   * parameter rather than a constant. Levels clamp at 6.
   */
  headingOffset?: number;
}

export function renderMarkdown(src: string, options: MarkdownOptions = {}): string {
  const offset = Math.max(0, options.headingOffset ?? 0);
  const escaped = escapeHtml(src ?? "");
  const blocks = escaped.split(/\n{2,}/);
  const html: string[] = [];
  for (const block of blocks) {
    const h = block.match(/^(#{1,6})\s+(.*)$/);
    if (h) {
      const level = Math.min(6, h[1].length + offset);
      html.push(`<h${level}>${inline(h[2])}</h${level}>`);
      continue;
    }
    const lines = block.split("\n");
    if (lines.every((l) => /^\s*[-*]\s+/.test(l))) {
      const items = lines.map((l) => `<li>${inline(l.replace(/^\s*[-*]\s+/, ""))}</li>`);
      html.push(`<ul>${items.join("")}</ul>`);
      continue;
    }
    html.push(`<p>${inline(block.replace(/\n/g, "<br/>"))}</p>`);
  }
  return html.join("\n");
}

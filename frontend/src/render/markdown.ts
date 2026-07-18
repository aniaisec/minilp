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

export function renderMarkdown(src: string): string {
  const escaped = escapeHtml(src ?? "");
  const blocks = escaped.split(/\n{2,}/);
  const html: string[] = [];
  for (const block of blocks) {
    const h = block.match(/^(#{1,6})\s+(.*)$/);
    if (h) {
      const level = h[1].length;
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

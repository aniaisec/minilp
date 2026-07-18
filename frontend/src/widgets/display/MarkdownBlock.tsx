import { renderMarkdown } from "../../render/markdown";
import { resolveSource } from "../../render/resolve";
import { asString, type DisplayWidgetProps } from "./types";

// Markdown display block (safe subset). render.collapsible supported (§2.2).
export function MarkdownBlock({ block, payload }: DisplayWidgetProps) {
  const src = asString(resolveSource(payload, block.source ?? ""));
  const html = renderMarkdown(src);
  const body = (
    <div
      className="mlp-block-markdown"
      data-testid="markdown-block"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
  if (block.render?.collapsible) {
    return (
      <details className="mlp-card mlp-collapsible mlp-block" open>
        <summary>Details</summary>
        {body}
      </details>
    );
  }
  return <div className="mlp-card mlp-block">{body}</div>;
}

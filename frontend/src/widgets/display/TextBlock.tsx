import { resolveSource } from "../../render/resolve";
import { asString, type DisplayWidgetProps } from "./types";

// Plain-text display block. Supports render.collapsible and render.max_lines (§2.2).
export function TextBlock({ block, payload }: DisplayWidgetProps) {
  const text = asString(resolveSource(payload, block.source ?? ""));
  const render = block.render ?? {};
  const maxLines = typeof render.max_lines === "number" ? render.max_lines : undefined;
  const style = maxLines
    ? {
        display: "-webkit-box",
        WebkitLineClamp: maxLines,
        WebkitBoxOrient: "vertical" as const,
        overflow: "hidden",
      }
    : undefined;

  const body = (
    <div className="mlp-block-text" style={style} data-testid="text-block">
      {text}
    </div>
  );

  if (render.collapsible) {
    return (
      <details className="mlp-card mlp-collapsible mlp-block" open>
        <summary>Text</summary>
        {body}
      </details>
    );
  }
  return <div className="mlp-card mlp-block">{body}</div>;
}

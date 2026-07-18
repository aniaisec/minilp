import { resolveSource } from "../../render/resolve";
import { asString, type DisplayWidgetProps } from "./types";

// Code display block. render.language label, render.line_numbers (§2.2).
// Syntax highlighting is a post-v1 concern; structure + line numbers ship now.
export function CodeBlock({ block, payload }: DisplayWidgetProps) {
  const code = asString(resolveSource(payload, block.source ?? ""));
  const render = block.render ?? {};
  const lines = code.split("\n");
  const showNums = !!render.line_numbers;
  return (
    <div className="mlp-card mlp-block mlp-block-code">
      {render.language ? <div className="mlp-muted">{String(render.language)}</div> : null}
      <pre className="mlp-code" data-testid="code-block">
        <code>
          {lines.map((ln, i) => (
            <div key={i}>
              {showNums ? (
                <span className="mlp-muted" style={{ userSelect: "none", marginRight: 12 }}>
                  {String(i + 1).padStart(3, " ")}
                </span>
              ) : null}
              {ln}
            </div>
          ))}
        </code>
      </pre>
    </div>
  );
}

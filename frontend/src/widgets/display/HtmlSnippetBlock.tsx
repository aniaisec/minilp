import { resolveSource } from "../../render/resolve";
import { asString, type DisplayWidgetProps } from "./types";

// HTML snippet display block, sandboxed in an iframe (§2.1: "html_snippet (sandboxed)").
// The sandbox attribute has no allow-scripts, so embedded JS can't run.
export function HtmlSnippetBlock({ block, payload }: DisplayWidgetProps) {
  const html = asString(resolveSource(payload, block.source ?? ""));
  return (
    <div className="mlp-card mlp-block mlp-block-html">
      <iframe
        title="content"
        data-testid="html-snippet-block"
        sandbox=""
        srcDoc={html}
        style={{ width: "100%", border: "none", minHeight: 120, background: "#fff" }}
      />
    </div>
  );
}

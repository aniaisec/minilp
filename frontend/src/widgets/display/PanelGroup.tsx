import { renderMarkdown } from "../../render/markdown";
import { orderedPanelSources, resolveSource } from "../../render/resolve";
import { asString, type DisplayWidgetProps } from "./types";

// N side-by-side panels drawn from the unit payload per the active variant (§2.1).
// Blinded: panels are labelled neutrally ("Response 1/2"); A/B identity and the
// variant value are never shown to the annotator (§1.3, §11).
export function PanelGroup({ block, payload, variant }: DisplayWidgetProps) {
  const ordered = orderedPanelSources(block, variant);
  const syncScroll = block.render?.sync_scroll ? "sync" : undefined;
  return (
    <div
      className="mlp-panel-group"
      data-testid="panel-group"
      data-sync-scroll={syncScroll}
      style={{ ["--panel-count" as string]: String(ordered.length) }}
    >
      {ordered.map((p, i) => {
        const content = asString(resolveSource(payload, p.source));
        return (
          <div
            key={p.source}
            className="mlp-card mlp-panel"
            data-panel-index={i}
            data-testid={`panel-${i}`}
          >
            <div className="mlp-muted" style={{ marginBottom: 8 }}>
              Response {i + 1}
            </div>
            <div dangerouslySetInnerHTML={{ __html: renderMarkdown(content) }} />
          </div>
        );
      })}
    </div>
  );
}

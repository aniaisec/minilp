import { resolveSource } from "../../render/resolve";
import { asString, type DisplayWidgetProps } from "./types";

// Image display block. render.fit (contain|cover), render.zoom, render.lightbox (§2.2).
export function ImageBlock({ block, payload }: DisplayWidgetProps) {
  const url = asString(resolveSource(payload, block.source ?? ""));
  const render = block.render ?? {};
  const fit = render.fit === "cover" ? "cover" : "contain";
  const classes = ["mlp-card", "mlp-block", "mlp-block-image", `fit-${fit}`];
  if (render.zoom) classes.push("zoomable");
  return (
    <div className={classes.join(" ")}>
      {url ? (
        <img
          src={url}
          alt=""
          data-testid="image-block"
          style={{ objectFit: fit as "contain" | "cover", width: "100%" }}
        />
      ) : (
        <div className="mlp-muted">no image</div>
      )}
    </div>
  );
}

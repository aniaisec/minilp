import { useRef, useState } from "react";
import { resolveSource } from "../../render/resolve";
import { asString, type DisplayWidgetProps } from "./types";

const SPEEDS = [0.75, 1, 1.25, 1.5, 2];

// Audio display block. render.waveform (indicator), render.playback_speed control (§2.2).
export function AudioBlock({ block, payload }: DisplayWidgetProps) {
  const url = asString(resolveSource(payload, block.source ?? ""));
  const render = block.render ?? {};
  const audioRef = useRef<HTMLAudioElement>(null);
  const [speed, setSpeed] = useState(1);

  const showSpeed = render.playback_speed !== false;

  return (
    <div className="mlp-card mlp-block mlp-block-audio">
      {render.waveform ? <div className="mlp-muted" aria-hidden>≈≈≈ waveform ≈≈≈</div> : null}
      {url ? (
        <audio ref={audioRef} src={url} controls data-testid="audio-block" style={{ width: "100%" }} />
      ) : (
        <div className="mlp-muted">no audio</div>
      )}
      {showSpeed ? (
        <label className="mlp-muted" style={{ display: "flex", gap: 8, alignItems: "center" }}>
          Speed
          <select
            value={speed}
            onChange={(e) => {
              const s = Number(e.target.value);
              setSpeed(s);
              if (audioRef.current) audioRef.current.playbackRate = s;
            }}
          >
            {SPEEDS.map((s) => (
              <option key={s} value={s}>
                {s}×
              </option>
            ))}
          </select>
        </label>
      ) : null}
    </div>
  );
}

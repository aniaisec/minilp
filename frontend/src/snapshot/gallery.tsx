// A specimen sheet of the shared primitives, for the phase-5 before/after pair.
//
// Why this is raw markup rather than `<Button variant="ghost">`:
//
// The "before" snapshot is built from a tree checked out at `main`, with only
// `src/snapshot/` and `scripts/` overlaid from the branch. That is what makes a
// real before/after possible — the same scenarios, rendered by two different
// versions of the app. It also means anything in this directory has to compile
// against *both* trees, and `src/components/ui.tsx` does not exist on `main`.
//
// So this file writes the class names the `Button` component emits, rather than
// importing it. The comparison is honest either way: on `main` none of the
// variant or size rules exist, so every button renders identically — which is
// precisely the problem phase 5 is fixing, shown rather than asserted.

const VARIANTS = ["primary", "secondary", "ghost", "danger"] as const;
const SIZES = ["sm", "md", "lg"] as const;

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10 }}>
      <span
        className="mlp-muted"
        style={{ width: 92, flexShrink: 0, fontSize: 12, textTransform: "uppercase" }}
      >
        {label}
      </span>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        {children}
      </div>
    </div>
  );
}

function btn(variant: string, size?: string) {
  return `mlp-btn mlp-btn-${variant}${size && size !== "md" ? ` mlp-btn-${size}` : ""}`;
}

export function Gallery() {
  return (
    <div className="mlp-admin-main" style={{ maxWidth: 1000, padding: 24 }}>
      <h1 style={{ fontSize: 22, margin: "0 0 4px" }}>Shared primitives</h1>
      <p className="mlp-muted" style={{ margin: "0 0 20px" }}>
        Buttons, card headers, tables and the empty/error states — UX plan phase 5.
      </p>

      <div className="mlp-stack-lg" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {/* ---- buttons ---- */}
        <section className="mlp-card">
          <div className="mlp-card-head">
            <div className="mlp-card-heading">
              <h2 className="mlp-card-title">Buttons</h2>
              <p className="mlp-card-desc">
                Four variants, three sizes, one disabled appearance. Before phase 5 there was one
                button and a scattering of inline overrides.
              </p>
            </div>
            <div className="mlp-card-actions">
              <button type="button" className={btn("secondary")}>
                Header action
              </button>
            </div>
          </div>

          <Row label="variants">
            {VARIANTS.map((v) => (
              <button type="button" key={v} className={btn(v)}>
                {v}
              </button>
            ))}
          </Row>
          <Row label="sizes">
            {SIZES.map((s) => (
              <button type="button" key={s} className={btn("primary", s)}>
                {s === "md" ? "md (default)" : s}
              </button>
            ))}
          </Row>
          <Row label="sizes">
            {SIZES.map((s) => (
              <button type="button" key={s} className={btn("secondary", s)}>
                {s === "md" ? "md (default)" : s}
              </button>
            ))}
          </Row>
          <Row label="disabled">
            {VARIANTS.map((v) => (
              <button type="button" key={v} className={btn(v)} disabled>
                {v}
              </button>
            ))}
          </Row>
          <Row label="with badge">
            <button type="button" className={btn("primary")}>
              Submit <kbd className="mlp-badge">⏎</kbd>
            </button>
            <button type="button" className={btn("secondary")}>
              Skip <kbd className="mlp-badge">s</kbd>
            </button>
          </Row>
        </section>

        {/* ---- table ---- */}
        <section className="mlp-card">
          <div className="mlp-card-head">
            <div className="mlp-card-heading">
              <h2 className="mlp-card-title">Table</h2>
              <p className="mlp-card-desc">
                Sticky header, row hover, a named action column, and a defined empty state.
              </p>
            </div>
          </div>
          <table className="mlp-table">
            <caption className="mlp-visually-hidden">Specimen table</caption>
            <thead>
              <tr>
                <th scope="col">id</th>
                <th scope="col">status</th>
                <th scope="col">gold</th>
                <th scope="col">
                  <span className="mlp-visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {[
                { id: 4821, status: "finalized", gold: false },
                { id: 4822, status: "labeled", gold: true },
                { id: 4823, status: "pending", gold: false },
              ].map((u) => (
                <tr key={u.id}>
                  <td className="mlp-mono">#{u.id}</td>
                  <td>{u.status}</td>
                  <td>{u.gold ? <span className="mlp-pill mlp-pill-warn">gold</span> : ""}</td>
                  <td>
                    <button type="button" className={btn("ghost", "sm")}>
                      detail
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        {/* ---- states ---- */}
        <section className="mlp-card">
          <div className="mlp-card-head">
            <div className="mlp-card-heading">
              <h2 className="mlp-card-title">Empty and error states</h2>
              <p className="mlp-card-desc">
                Both were a bare sentence in a card, or — for errors — the raw text the fetch
                rejected with, announced to nobody.
              </p>
            </div>
          </div>

          <div className="mlp-state" role="status">
            <svg
              width="28"
              height="28"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={1.8}
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
              focusable="false"
              className="mlp-state-icon"
            >
              <path d="M3 13h4l1.6 3h6.8l1.6-3h4" />
              <path d="M5.5 4.5h13l2.5 8.5v4.5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V13l2.5-8.5Z" />
            </svg>
            <div>
              <p className="mlp-state-title">No units match these filters</p>
              <p className="mlp-state-body">
                Widen the filters above, or add tasks to this project from the Add tasks section.
              </p>
              <div className="mlp-state-actions">
                <button type="button" className={btn("primary")}>
                  Clear filters
                </button>
              </div>
            </div>
          </div>

          <div className="mlp-state mlp-state-error mlp-state-inline" role="alert">
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={1.8}
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
              focusable="false"
              className="mlp-state-icon"
            >
              <path d="M10.3 3.8 2.6 17.1A2 2 0 0 0 4.3 20h15.4a2 2 0 0 0 1.7-2.9L13.7 3.8a2 2 0 0 0-3.4 0Z" />
              <path d="M12 9v4.5" />
              <path d="M12 17h.01" />
            </svg>
            <div>
              <p className="mlp-state-title">The import failed</p>
              <p className="mlp-state-body">
                bundle_version 2 is newer than this instance understands (max 1)
              </p>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

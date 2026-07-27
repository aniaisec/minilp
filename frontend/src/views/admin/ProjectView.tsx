// Per-project admin surface (§11): tabbed between progress, the unit browser,
// bias/analytics, the annotator roster and — from M6 — configuration, adding
// tasks, and export.

import { useState } from "react";

import type { MiniLpClient } from "../../api/client";
import { AddTasksPanel } from "./AddTasksPanel";
import { BiasPanel } from "./BiasPanel";
import { ConfigPanel } from "./ConfigPanel";
import { ExportPanel } from "./ExportPanel";
import { ProgressPanel } from "./ProgressPanel";
import { RosterPanel } from "./RosterPanel";
import { UnitBrowser } from "./UnitBrowser";

type Tab = "progress" | "units" | "bias" | "roster" | "config" | "add" | "export";
const TABS: { id: Tab; label: string }[] = [
  { id: "progress", label: "Progress" },
  { id: "units", label: "Units" },
  { id: "bias", label: "Bias & distribution" },
  { id: "roster", label: "Annotators" },
  { id: "config", label: "Configure" },
  { id: "add", label: "Add tasks" },
  { id: "export", label: "Export" },
];

export function ProjectView({
  client,
  projectId,
  onBack,
}: {
  client: MiniLpClient;
  projectId: number;
  onBack: () => void;
}) {
  const [tab, setTab] = useState<Tab>("progress");

  return (
    <div className="mlp-stack-lg" style={{ maxWidth: "var(--content-xl)" }}>
      <div className="mlp-actions" style={{ gap: 12 }}>
        <button className="mlp-btn" onClick={onBack}>
          ← projects
        </button>
        <h2 style={{ margin: 0 }}>Project #{projectId}</h2>
      </div>

      <div className="mlp-tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={t.id === tab ? "mlp-tab mlp-tab-active" : "mlp-tab"}
            data-testid={`tab-${t.id}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "progress" && <ProgressPanel client={client} projectId={projectId} />}
      {tab === "units" && <UnitBrowser client={client} projectId={projectId} />}
      {tab === "bias" && <BiasPanel client={client} projectId={projectId} />}
      {tab === "roster" && <RosterPanel client={client} projectId={projectId} />}
      {tab === "config" && <ConfigPanel client={client} projectId={projectId} />}
      {tab === "add" && <AddTasksPanel client={client} projectId={projectId} />}
      {tab === "export" && <ExportPanel client={client} projectId={projectId} />}
    </div>
  );
}

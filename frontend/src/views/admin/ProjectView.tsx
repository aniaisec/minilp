// Per-project admin surface (§11): tabbed between progress, the unit browser,
// bias/analytics, the annotator roster and — from M6 — configuration, adding
// tasks, and export. M7 adds Judges: enrollment, dry-run costing, runs, spend
// against caps, and the webhook alerts that make an unattended run safe.

import { useState } from "react";

import type { MiniLpClient } from "../../api/client";
import { ActiveLearningPanel } from "./ActiveLearningPanel";
import { AddTasksPanel } from "./AddTasksPanel";
import { BiasPanel } from "./BiasPanel";
import { ConfigPanel } from "./ConfigPanel";
import { ExportPanel } from "./ExportPanel";
import { JudgesPanel } from "./JudgesPanel";
import { ProgressPanel } from "./ProgressPanel";
import { RosterPanel } from "./RosterPanel";
import { StartLabeling } from "./StartLabeling";
import { UnitBrowser } from "./UnitBrowser";
import { WebhooksPanel } from "./WebhooksPanel";

type Tab =
  | "progress"
  | "units"
  | "bias"
  | "roster"
  | "judges"
  | "active-learning"
  | "config"
  | "add"
  | "export";
const TABS: { id: Tab; label: string }[] = [
  { id: "progress", label: "Progress" },
  { id: "units", label: "Units" },
  { id: "bias", label: "Bias & distribution" },
  { id: "roster", label: "Annotators" },
  { id: "judges", label: "Judges" },
  { id: "active-learning", label: "Active learning" },
  { id: "config", label: "Configure" },
  { id: "add", label: "Add tasks" },
  { id: "export", label: "Export" },
];

// Most tabs read better in a column. "Configure" holds the template builder,
// which wants the room — capping it there would squeeze the live preview back
// out of view, which is the whole thing the side-by-side layout fixes.
const WIDE_TABS = new Set<Tab>(["config"]);

export function ProjectView({
  client,
  projectId,
  apiKey,
}: {
  client: MiniLpClient;
  projectId: number;
  /** Carried into the annotation-view URL so "Start labeling" needs no re-auth. */
  apiKey: string;
}) {
  const [tab, setTab] = useState<Tab>("progress");

  return (
    <div
      className="mlp-stack-lg"
      style={{ maxWidth: WIDE_TABS.has(tab) ? "none" : "var(--content-xl)" }}
    >
      <div className="mlp-actions" style={{ gap: 12 }}>
        {/* No "← projects" button and no heading here any more: the shell's
            breadcrumb is the way back and its `<h1>` names the project. Two
            controls doing the same job, one of them a second title, is what the
            command bar exists to replace. */}
        {/* Exit to home (M8, §11): every project screen carries a visible way
            back to the annotator home, this one included. It resolves the
            admin's own rater record on click, the same bridge "Start labeling"
            uses — an admin who has never labeled still has somewhere to land. */}
        <StartLabeling
          client={client}
          apiKey={apiKey}
          label="← Home"
          className="mlp-btn mlp-btn-exit"
        />
        <div style={{ marginLeft: "auto" }}>
          <StartLabeling client={client} projectId={projectId} apiKey={apiKey} />
        </div>
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
      {tab === "judges" && (
        <>
          <JudgesPanel client={client} projectId={projectId} />
          <WebhooksPanel client={client} projectId={projectId} />
        </>
      )}
      {tab === "active-learning" && <ActiveLearningPanel client={client} projectId={projectId} />}
      {tab === "config" && <ConfigPanel client={client} projectId={projectId} />}
      {tab === "add" && <AddTasksPanel client={client} projectId={projectId} />}
      {tab === "export" && <ExportPanel client={client} projectId={projectId} />}
    </div>
  );
}

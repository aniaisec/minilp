// Fixture API responses for the visual-snapshot harness (scripts/snapshot.mjs).
//
// These exist so a screenshot of the admin surface can be produced from a static
// file, with no backend and no database — the shell is what is under review, and
// the shell should not depend on someone's local data to be reviewable. The
// numbers are deliberately unround so the layout is exercised by realistic
// widths rather than by "100 / 100 / 100".

export const PROJECTS = [
  {
    id: 1,
    name: "Image QA · furniture catalogue",
    description: "Is the product visible, in focus, and correctly framed?",
    template_id: 4,
    template_version: 3,
    labels_per_unit: 3,
    gold_ratio: 0.08,
  },
  {
    id: 2,
    name: "Support ticket triage",
    description: "Route inbound tickets to the right queue and severity.",
    template_id: 7,
    template_version: 1,
    labels_per_unit: 2,
    gold_ratio: 0.05,
  },
  {
    id: 3,
    name: "Summary preference (A/B)",
    description: "Pairwise preference between two candidate summaries.",
    template_id: 9,
    template_version: 2,
    labels_per_unit: 5,
    gold_ratio: 0.1,
  },
];

export const PROGRESS = {
  project_id: 1,
  labels_per_unit: 3,
  max_labels_per_unit: 5,
  funnel: {
    pending: 412,
    in_progress: 37,
    labeled: 289,
    finalized: 1104,
    total: 1842,
    escalated: 6,
  },
  slots: { open: 1273, leased: 37, filled: 4181, voided: 12 },
  labels_total: 4181,
  batches: [
    {
      batch_id: 11,
      name: "catalogue-2024-q3.jsonl",
      unit_count: 1200,
      rejected_count: 4,
      status_counts: { pending: 210, labeled: 190, finalized: 800 },
      done: 990,
      total: 1200,
      fill_rate: 0.825,
    },
    {
      batch_id: 12,
      name: "catalogue-2024-q4.jsonl",
      unit_count: 642,
      rejected_count: 0,
      status_counts: { pending: 202, labeled: 99, finalized: 341 },
      done: 440,
      total: 642,
      fill_rate: 0.685,
    },
  ],
  variants: {
    dimension: "order",
    balanced: true,
    values: [
      { value: "ab", filled: 2103, open: 631, leased: 18, total: 2752, fill_rate: 0.764 },
      { value: "ba", filled: 2078, open: 642, leased: 19, total: 2739, fill_rate: 0.759 },
    ],
  },
  consensus: {
    complete_units: 1104,
    keys: {
      visible: { agreed: 1041, complete: 1104, rate: 0.943 },
      in_focus: { agreed: 968, complete: 1104, rate: 0.877 },
      framing: { agreed: 812, complete: 1104, rate: 0.736 },
    },
  },
  throughput: {
    labels_per_hour: 63.4,
    window_hours: 24,
    labels_in_window: 1522,
    remaining_slots: 1273,
    eta_hours: 20.1,
  },
};

export const TEMPLATES = [
  {
    id: 4,
    name: "Image QA",
    version: 3,
    schema: { layout: "stack", display: [], inputs: [] },
  },
  {
    id: 7,
    name: "Ticket triage",
    version: 1,
    schema: { layout: "stack", display: [], inputs: [] },
  },
];

/** Route table for the fetch stub: first matching pattern wins. */
export const ROUTES: [RegExp, unknown][] = [
  [/\/api\/projects\/\d+\/progress/, PROGRESS],
  [/\/api\/projects\/\d+$/, { ...PROJECTS[0], config: {} }],
  [/\/api\/projects$/, PROJECTS],
  [/\/api\/templates$/, TEMPLATES],
  [/\/api\/me:annotator/, { id: 42, display_name: "you" }],
];

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

export const BATCHES = [
  {
    id: 11,
    project_id: 1,
    name: "catalogue-2024-q3.jsonl",
    source_filename: "catalogue-2024-q3.jsonl",
    unit_count: 1200,
    rejected_count: 4,
  },
  {
    id: 12,
    project_id: 1,
    name: "catalogue-2024-q4.jsonl",
    source_filename: "catalogue-2024-q4.jsonl",
    unit_count: 642,
    rejected_count: 1,
  },
];

// A deliberately mixed page: two statuses, a gold, and an off-default priority,
// so the unit browser's pills and columns are all exercised by the snapshot
// rather than showing one repeated row.
export const UNITS = [
  {
    id: 4821,
    project_id: 1,
    batch_id: 11,
    payload: { image_url: "cdn/chairs/oak-dining-04.jpg", sku: "OAK-D-04" },
    priority: 0.5,
    is_gold: false,
    status: "finalized",
  },
  {
    id: 4822,
    project_id: 1,
    batch_id: 11,
    payload: { image_url: "cdn/lamps/brass-arc-11.jpg", sku: "BRS-A-11" },
    priority: 0.5,
    is_gold: true,
    status: "finalized",
  },
  {
    id: 4823,
    project_id: 1,
    batch_id: 12,
    payload: { image_url: "cdn/sofas/linen-3seat-02.jpg", sku: "LIN-S-02" },
    priority: 0.9,
    is_gold: false,
    status: "labeled",
  },
  {
    id: 4824,
    project_id: 1,
    batch_id: 12,
    payload: { image_url: "cdn/desks/walnut-standing-07.jpg", sku: "WAL-D-07" },
    priority: 0.5,
    is_gold: false,
    status: "in_progress",
  },
  {
    id: 4825,
    project_id: 1,
    batch_id: 12,
    payload: { image_url: "cdn/rugs/kilim-runner-19.jpg", sku: "KIL-R-19" },
    priority: 0.5,
    is_gold: false,
    status: "pending",
  },
];

/* -------------------------------------------------------------------------
   Labeler surface (phase 4).

   The annotation view is mounted directly rather than routed to, because its
   config lives in the query string and a `file://` snapshot cannot carry one
   reliably. Mounting `Annotate` with a fixture client is also closer to what
   is under review: the task bar, the rail footer and the widgets, not the
   query-string plumbing that picks a project.
   ------------------------------------------------------------------------- */

/** A self-contained stand-in for the unit's photo — no network, no asset dir. */
const SWATCH =
  "data:image/svg+xml;utf8," +
  encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="420" viewBox="0 0 640 420">
       <rect width="640" height="420" fill="#e7e2d8"/>
       <rect x="150" y="120" width="340" height="26" rx="6" fill="#8b6f4e"/>
       <rect x="168" y="146" width="18" height="150" fill="#8b6f4e"/>
       <rect x="454" y="146" width="18" height="150" fill="#8b6f4e"/>
       <rect x="150" y="86" width="340" height="34" rx="10" fill="#a9855f"/>
       <text x="320" y="380" font-family="system-ui" font-size="22" fill="#6b625a"
             text-anchor="middle">oak dining chair · OAK-D-04</text>
     </svg>`,
  );

/** Deliberately multi-input: one widget of each kind the phase-4 audit touched,
 *  so the rail is long enough that the sticky footer has something to prove. */
export const LABEL_SCHEMA = {
  name: "image-qa",
  version: 3,
  description: "Is the product visible, in focus, and correctly framed?",
  layout: { arrangement: "split", ratio: [3, 2], width: "xl" },
  display: [
    { type: "image", source: "$unit.image_url", render: { fit: "contain", zoom: true } },
    { type: "text", source: "$unit.context", optional: true, render: { max_lines: 8 } },
  ],
  inputs: [
    {
      id: "category",
      type: "radio",
      label: "What is shown?",
      options: ["chair", "table", "lamp", "rug"],
      allow_other: true,
      required: true,
      hotkeys: "auto",
    },
    {
      id: "framing",
      type: "rating",
      label: "Framing quality",
      scale: { points: 5, labels: ["unusable", "poor", "ok", "good", "excellent"] },
      required: true,
    },
    {
      id: "issues",
      type: "ranking",
      label: "Rank the issues, worst first",
      options: ["blurry", "cropped", "bad lighting", "cluttered"],
    },
    { id: "notes", type: "free_text", label: "Anything else worth flagging?", help: "Optional." },
  ],
  variants: null,
};

export const LABEL_GUIDELINES = [
  "Judge the **photo**, not the product.",
  "",
  "- A product half out of frame is `cropped`, even if it is sharp.",
  "- Shadow across the product is `bad lighting`, not `unusable`.",
  "- When two labels fit, pick the one a shopper would complain about first.",
].join("\n");

export const LABEL_TASK = {
  slot_id: 90210,
  unit_id: 4821,
  project_id: 1,
  payload: {
    image_url: SWATCH,
    context: "Catalogue batch catalogue-2024-q3.jsonl · supplier photo, unedited.",
  },
  variant: null,
};

/** Route table for the fetch stub: first matching pattern wins. */
export const ROUTES: [RegExp, unknown][] = [
  [/\/api\/projects\/\d+\/progress/, PROGRESS],
  [/\/api\/projects\/\d+\/batches/, BATCHES],
  [/\/api\/projects\/\d+\/units/, UNITS],
  [/\/api\/projects\/\d+$/, { ...PROJECTS[0], config: {} }],
  [/\/api\/projects$/, PROJECTS],
  [/\/api\/templates$/, TEMPLATES],
  [/\/api\/me:annotator/, { id: 42, display_name: "you" }],
];

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
    kind: "custom",
    schema: { layout: "stack", display: [], inputs: [] },
  },
  {
    id: 7,
    name: "Ticket triage",
    version: 1,
    kind: "custom",
    schema: { layout: "stack", display: [], inputs: [] },
  },
];

/** Phase 7: the delete control stays disabled until its usage call answers, so
 *  the confirmation scenario needs one. Three versions and no blocking project
 *  — that is the state where the dialog has something interesting to say, since
 *  the lineage checkbox changes what the confirm button is offering to do. */
export const TEMPLATE_USAGE = {
  template_id: 4,
  name: "Image QA",
  versions: 3,
  deletable: true,
  projects: [],
  lineage_projects: [],
};

export const TEMPLATE_SAMPLE = {
  template_id: 4,
  saved: true,
  sample: { image_url: "https://cdn.example.com/catalogue/00412.jpg", sku: "CH-00412" },
  fields: { required: ["image_url"], optional: ["sku"] },
};

/** Phase 7: a registered hook, so removing one can be the frame that shows a
 *  toast on a real screen rather than on a specimen sheet. */
export const WEBHOOKS = [
  {
    id: 3,
    project_id: 1,
    event: "budget.cap_reached",
    target_url: "https://hooks.example.com/minilp/budget",
    has_secret: true,
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
// The judges section (phase 5). It is the densest screen in the admin surface —
// a table with a per-row action, three cards with headers, and a set of buttons
// that spans every variant — which is exactly why it is the one worth a frame.
export const ENROLLED_JUDGES = {
  project_id: 1,
  judges: [
    {
      judge_config_id: 1,
      annotator_id: 91,
      display_name: "catalogue-grader v3",
      provider: "anthropic",
      model_id: "claude-sonnet-4",
      prompt_version: 3,
      budget: { project_usd: 40, daily_usd: 12 },
      priced: true,
      price_source: "table:claude-sonnet-4",
      spend: { cost_usd: 27.42, daily_usd: 8.15, tokens: 1_284_900, labels: 1631, cache_hits: 402 },
    },
    {
      judge_config_id: 2,
      annotator_id: 92,
      display_name: "local-ft v2",
      provider: "openai_compatible",
      model_id: "furniture-ft-v2",
      prompt_version: 2,
      budget: null,
      // Unpriced on purpose: the "unpriced, not $0.00" distinction is one of the
      // things a reviewer should be able to see in the frame.
      priced: false,
      price_source: null,
      spend: { cost_usd: 0, daily_usd: 0, tokens: 318_400, labels: 407, cache_hits: 0 },
    },
  ],
};

export const JUDGE_CONFIGS = [
  { id: 1, name: "catalogue-grader", provider: "anthropic", model_id: "claude-sonnet-4", prompt_version: 3 },
  { id: 2, name: "local-ft", provider: "openai_compatible", model_id: "furniture-ft-v2", prompt_version: 2 },
  { id: 3, name: "strict-framing", provider: "openai", model_id: "gpt-4o-mini", prompt_version: 1 },
];

export const COSTS = {
  project_id: 1,
  totals: {
    cost_usd: 27.42,
    cost_per_judge_label: 0.0134,
    judge_labels: 2038,
    human_labels: 2143,
    cache_hit_rate: 0.197,
    tokens: 1_603_300,
  },
  judges: [
    {
      annotator_id: 91,
      display_name: "catalogue-grader v3",
      labels: 1631,
      cost_usd: 27.42,
      cost_per_label: 0.0168,
      cache_hit_rate: 0.246,
      avg_latency_ms: 1840,
    },
    {
      annotator_id: 92,
      display_name: "local-ft v2",
      labels: 407,
      cost_usd: 0,
      cost_per_label: 0,
      cache_hit_rate: 0,
      avg_latency_ms: 312,
    },
  ],
};

export const JUDGE_RUNS = [
  {
    id: 18,
    project_id: 1,
    judge_config_id: 1,
    annotator_id: 91,
    dry_run: false,
    status: "completed",
    stopped_reason: "budget_project",
    slots_attempted: 500,
    labels_written: 486,
    cache_hits: 121,
    tokens_in: 402_000,
    tokens_out: 38_400,
    cost_usd: 9.14,
    estimated_cost_usd: null,
  },
  {
    id: 17,
    project_id: 1,
    judge_config_id: 1,
    annotator_id: 91,
    dry_run: true,
    status: "completed",
    stopped_reason: "exhausted",
    slots_attempted: 500,
    labels_written: 0,
    cache_hits: 0,
    tokens_in: 398_100,
    tokens_out: 0,
    cost_usd: null,
    estimated_cost_usd: 9.06,
  },
];

export const ROUTES: [RegExp, unknown][] = [
  [/\/api\/projects\/\d+\/progress/, PROGRESS],
  [/\/api\/projects\/\d+\/batches/, BATCHES],
  [/\/api\/projects\/\d+\/units/, UNITS],
  [/\/api\/projects\/\d+\/judges/, ENROLLED_JUDGES],
  [/\/api\/projects\/\d+\/judge-runs/, JUDGE_RUNS],
  [/\/api\/projects\/\d+\/analytics\/costs/, COSTS],
  [/\/api\/projects\/\d+$/, { ...PROJECTS[0], config: {} }],
  [/\/api\/projects$/, PROJECTS],
  [/\/api\/judges\/providers/, { providers: ["mock", "anthropic", "openai", "openai_compatible"] }],
  [/\/api\/judges$/, JUDGE_CONFIGS],
  [/\/api\/webhooks/, WEBHOOKS],
  // Ahead of the bare `/templates` pattern: the list route would otherwise
  // swallow `/templates/4/usage` too, since it is only anchored at the end.
  [/\/api\/templates\/\d+\/usage/, TEMPLATE_USAGE],
  [/\/api\/templates\/\d+\/sample/, TEMPLATE_SAMPLE],
  [/\/api\/templates\/\d+$/, TEMPLATES[0]],
  [/\/api\/templates$/, TEMPLATES],
  [/\/api\/me:annotator/, { id: 42, display_name: "you" }],
];

// The same surface with nothing in it. One override rather than a second
// fixture file: the empty state is a property of the *panel*, and swapping the
// data underneath the real panel is the only way to see the real thing.
export const EMPTY_ROUTES: [RegExp, unknown][] = [
  // A zeroed funnel rather than no fixture at all: the point of the empty
  // scenarios is the empty state, and a header reading "summary unavailable"
  // beside it would put an unrelated failure in the frame.
  [
    /\/api\/projects\/\d+\/progress/,
    {
      ...PROGRESS,
      funnel: { pending: 0, in_progress: 0, labeled: 0, finalized: 0, total: 0, escalated: 0 },
      slots: { open: 0, leased: 0, filled: 0, voided: 0 },
      labels_total: 0,
      batches: [],
      variants: { dimension: null, balanced: true, values: [] },
      consensus: { complete_units: 0, keys: {} },
      throughput: { labels_per_hour: 0, eta_hours: null, remaining_slots: 0 },
    },
  ],
  [/\/api\/projects\/\d+\/batches/, []],
  [/\/api\/projects\/\d+\/units/, []],
  [/\/api\/projects\/\d+\/annotators/, { project_id: 1, count: 0, annotators: [] }],
  [/\/api\/projects\/\d+\/judges/, { project_id: 1, judges: [] }],
  [/\/api\/projects\/\d+\/judge-runs/, []],
  [/\/api\/projects\/\d+\/analytics\/costs/, { ...COSTS, judges: [] }],
  [/\/api\/projects\/\d+$/, { ...PROJECTS[0], config: {} }],
  [/\/api\/projects$/, []],
  [/\/api\/judges\/providers/, { providers: ["mock"] }],
  [/\/api\/judges$/, []],
  [/\/api\/webhooks/, []],
  [/\/api\/templates$/, []],
  [/\/api\/me:annotator/, { id: 42, display_name: "you" }],
];

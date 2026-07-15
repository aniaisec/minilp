# MiniLP — Mini Labeling Platform

A self-hostable, open-source platform for collecting **any type of label — from humans and model judges — through configurable task templates**, aimed at anyone fine-tuning a model for a specific scenario. Built-in quality controls: gold questions, inter-annotator agreement, rater reputation (which for model judges *is* calibration), ensemble merging with human escalation, and position-bias counterbalancing for comparison tasks.

Side-by-side preference judging is the flagship *built-in template*, not the product. The product is the template engine plus the labeling pipeline around it.

**Target location:** `C:\my\agents\Projects\MiniLP`
**Stack:** FastAPI (Python ≥3.12; CI/Docker on 3.14) · PostgreSQL · React + TypeScript (Vite) · Docker Compose
**Primary audience:** ML-savvy solo builders — docker compose, JSONL, API keys are fine; priorities are good defaults, an API-first design with documented curl/SDK snippets, and minimal clicks.
**Timeline:** M0–M6 = human-labeling MVP · M7–M9 = model judges, ensembles, active learning · M10 = marketplace

---

## 1. Core design principles

1. **Templates define everything the annotator sees and returns.** A template = layout (how the page is arranged) + display blocks (what to show, and how each renders) + input fields (which key-value pairs to collect, and their hotkeys) + optional variant rules (how presentation is balanced). Adding a new labeling type means writing a template, not writing code — and the fastest path is cloning an existing one and editing.
2. **Humans and model judges are the same thing to the system.** An annotator has `kind: human | model`. Both are assigned slots by the same engine, answer golds, accrue reputation, and count toward agreement. A judge's reputation is its measured calibration. Everything downstream (merge weights, gating) works uniformly.
3. **Store canonical data, present blinded data.** The database knows the ground truth about each unit (source models, expected answers, variant assignment). Annotators — human or model — see only what the template renders.
4. **Record raw and canonical answers.** For variant-balanced templates, every label stores both the raw input (side clicked) and the canonical value (item chosen) — position bias is measurable for judges too (LLMs have well-documented order bias).
5. **Quality is a pipeline, not a report.** Golds, agreement, and bias scores feed live reputation that gates assignment; ensemble labels merge by calibration weight and escalate to humans on disagreement.
6. **Schema-first for the future.** The M1 data model already carries annotator kind, judge configs, pipelines, and final labels — even though M1–M6 only exercise the human path. No migration pain when judges land.
7. **Guidelines are first-class.** Every project carries annotator instructions (markdown), shown as a collapsible panel in the annotation view — expanded on the annotator's first task, collapsed after, one keystroke to toggle. The same guidelines text is injected into judge prompts.

---

## 2. Template system (the core)

### 2.1 Template schema

A template is a versioned JSON document:

```jsonc
{
  "name": "image-classification",
  "version": 1,
  "layout": {                     // how the page is arranged (§2.2)
    "arrangement": "split",       // "stack" (default) | "split" | "columns"
    "ratio": [3, 2],              // relative region widths for split/columns
    "width": "xl"                 // content width token: md | lg | xl | full
  },
  "display": [                    // ordered blocks shown to the annotator
    { "type": "image", "source": "$unit.image_url",
      "render": { "fit": "contain", "zoom": true } },
    { "type": "text",  "source": "$unit.context", "optional": true,
      "render": { "collapsible": true, "max_lines": 12 } }
  ],
  "inputs": [                     // fields the annotator fills — each id becomes
    {                             // a key in the judgment object (§2.3)
      "id": "category",
      "type": "radio",
      "label": "What is shown in the image?",
      "options": ["cat", "dog", "bird"],
      "allow_other": true,        // renders an "Other…" option with free-text entry
      "required": true,
      "hotkeys": "auto"           // 1/2/3 + o for Other (§2.4)
    },
    {
      "id": "quality_flags",
      "type": "checkbox",
      "label": "Quality issues",
      "options": ["blurry", "multiple subjects"],
      "hotkeys": ["b", "m"],      // explicit letter overrides
      "required": false
    }
  ],
  "variants": null                // or a balancing spec, see §2.7
}
```

**Display block types (v1):** `text`, `markdown`, `image`, `audio`, `code` (syntax-highlighted), `html_snippet` (sandboxed), `panel_group` (N side-by-side panels, contents drawn from unit payload per the active variant).

**Input field types (v1):** `radio` (with `allow_other`), `checkbox` (multi-select, with `allow_other`), `likert` (labeled scale), `free_text`, `choice_buttons` (large keyboard-mapped buttons, e.g. Left/Tie/Right), `span_select` (highlight spans in a text block — stretch goal, may slip past M6).

`$unit.<key>` resolves against the unit's JSON payload at render time. Template + payload validation happens at upload: every unit is checked against the template's required sources before it enters the pool.

**Templates render for judges too:** each display/input type has a text serialization (images pass as URLs/attachments to multimodal judges), so a judge prompt is assembled mechanically from guidelines + serialized template + unit payload + answer-format instructions. One template drives both the human UI and the judge prompt.

### 2.2 Layout & rendering control

- **Arrangement:** `stack` (display blocks top-to-bottom, inputs below — the mobile-safe default), `split` (display region beside the input rail — classification at speed), `columns` (explicit regions with per-block placement — dense comparison layouts). `panel_group` manages its own interior columns in any arrangement.
- **Per-block `render` options,** validated per type: images (`fit`, `zoom`, lightbox), text/markdown (`collapsible`, `max_lines` with expand), code (`language`, line numbers), audio (waveform, playback-speed control), panels (`sync_scroll`, `diff_highlight` for near-identical outputs).
- **Design tokens, not free-form CSS:** templates choose from a fixed token set (width, density, panel emphasis); the app supplies the visual system — card-based surfaces, a typographic scale tuned for long reading, light/dark theme (annotator-toggleable, `d`), and motion kept to instant feedback (selection states, submit flash) so throughput never waits on animation. Modern, but never at the cost of speed.
- Layout and render options are presentation-only: they never affect stored values, so a template can be restyled mid-project without invalidating collected labels (schema-affecting edits still bump the version, §2.5).

### 2.3 Judgments are key-value objects

Every input `id` is a key; a submitted judgment is one JSON object:

```jsonc
// raw (what was entered)                  // value (canonicalized)
{ "category": "other:capybara",           { "category": "capybara",
  "quality_flags": ["blurry"] }             "quality_flags": ["blurry"] }
```

- Each input type declares its value shape (radio → string, checkbox → string array, likert → int, free_text → string, choice_buttons → enum) — this is what golds match against (per key), agreement is computed on (per key), and exports emit.
- `required` gates submission; optional keys may be absent.
- `show_if` (v1.1): conditional inputs, e.g. show `severity` only when a violation category is checked — the dependent key is only collected (and only graded) when its condition held.

### 2.4 Keyboard-first judging (hotkeys)

Every interactive element is reachable from the keyboard — numbers and letters judge; the mouse is optional:

- **Auto-assignment (`"hotkeys": "auto"`, the default):** the first choice-type input's options get `1…9`; subsequent inputs' options get letters (`a, b, c…`), skipping reserved keys. `allow_other` gets `o`. `likert` maps to `1…N`. `choice_buttons` may bind arrows (side-by-side keeps `←`/`↓`/`→`).
- **Explicit override:** any option can pin its key (`"hotkeys": ["b", "m"]`) — clones keep muscle memory stable when options are reordered.
- **Reserved:** `Enter` submit (auto-submits when the template has a single required input — one keystroke per task), `s` skip, `g` guidelines, `d` dark mode, `u` undo last selection, `?` hotkey overlay (dims the screen and badges every element with its key).
- **Validation:** hotkey conflicts (duplicate keys, reserved-key collisions) are template-validation errors at save time, not runtime surprises.
- Keys are rendered as small badges on each option — discoverable without the overlay.

### 2.5 Creating, cloning & versioning templates

The intended workflow is **clone → tweak → go**, not blank-page authoring:

- **Clone anything:** every gallery or custom template has a one-click *Use as starting point* (`POST /templates/{id}:clone`) producing an editable draft — built-ins are immutable, so cloning is also how you "edit" one.
- **Edit with live preview:** the template editor shows a validated JSON editor (schema-aware autocomplete for block/input/render types) beside a live preview rendering a sample unit — every change re-renders instantly, including layout, hotkey badges, and the `?` overlay. A visual (no-code) builder stays post-v1; the JSON editor with preview is the v1 bar for the ML-savvy audience.
- **Versioning:** presentation-only edits (layout, render options, hotkeys) update in place; schema-affecting edits (inputs added/removed/retyped, options changed, variants) bump the version. Units and labels pin the version they were collected under, so a running project is never silently re-shaped.
- **Draft → publish:** drafts are only attachable to projects once validation passes (payload refs resolve, hotkeys conflict-free, variant divisibility holds).

### 2.6 Extensibility contract

Adding a new input or display type touches exactly four places, documented in `docs/extending.md`:
1. JSON-schema fragment for the type's config (backend validation),
2. a React component registered in the frontend widget registry (declaring its render options and hotkey behavior),
3. an optional canonicalizer (raw answer → canonical value) on the backend,
4. a text/prompt serializer for judge consumption (a default exists; override when the naive rendering is lossy).

Everything else — assignment, leasing, golds, agreement, reputation, merging, export — is template-agnostic because it operates on JSON payloads and JSON answers.

### 2.7 Variants and counterbalancing (generalized from side-by-side)

Some templates present the same unit in multiple equivalent arrangements. A template may declare a **variant dimension**:

```jsonc
"variants": {
  "dimension": "panel_order",
  "values": ["AB", "BA"],
  "balance": "strict"   // slots pre-generated K/2 per value, K even (enforced)
}
```

Rules (applied to any variant-bearing template):
- `labels_per_unit = K` must be divisible by the number of variant values (default K=4 for 2 variants); slots are pre-generated with fixed variant values.
- **Across-annotator balancing:** an annotator never gets the same unit twice in any variant (repeats leak content memory — and would let a judge model see both orders).
- Slot assignment order is shuffled so sessions have no predictable variant rhythm.
- **Balance survives failures:** abandoned/expired/voided slots return to the pool *retaining their variant designation*. A unit is `complete` only when all K slots hold valid labels — guaranteeing exact balance at completion.
- Golds follow the same variant rules, so bias metrics on golds are comparable to real tasks.

Templates without variants (plain classification, rating) simply set `variants: null` and get one slot pool.

### 2.8 What gets stored per label

| Field | Meaning |
|---|---|
| `slot_id` | FK to the pre-generated slot (carries the variant value, if any) |
| `raw` | JSON: exactly what the annotator entered, per input id (e.g. `{"choice": "left"}`) |
| `value` | JSON: canonicalized answer (e.g. `{"choice": "A"}`); equals `raw` for variant-free templates |
| `confidence` | Optional self-reported confidence; for judges: elicited score or logprob-derived |
| `reasoning` | Optional rationale; for judges: the stored reasoning trace (shown in review queue) |
| `latency_ms`, `tokens_in/out`, `cost_usd`, `cache_hit` | Speed + judge cost provenance |
| `annotator_id`, `submitted_at` | Attribution (annotator carries kind + judge config version) |

---

## 3. Built-in example templates (the gallery)

Shipped as seed data; each is a full working example an admin can clone and edit. The gallery is also the test corpus for the template engine.

| Template | Shows | Collects | Variants |
|---|---|---|---|
| **Side-by-side preference** (flagship) | prompt + two blinded response panels | `choice_buttons`: Left / Tie / Right (keys `←` `↓` `→`) | `panel_order: AB/BA`, strict balance |
| **Image classification** | an image | `radio` with preset labels + **Other** (manual label entry) | — |
| **Text sentiment** | a text passage | `radio`: positive / neutral / negative + confidence `likert` 1–5 | — |
| **Summary quality rating** | source document + model summary | three `likert` scales: faithfulness, coverage, fluency + optional `free_text` comment | — |
| **Toxicity / policy review** | a text or html snippet | `checkbox` multi-select of violation categories + Other + severity `radio` | — |
| **Transcription check** | audio clip + candidate transcript | `radio`: correct / minor errors / wrong + `free_text` correction | — |
| **A/B/n ranking** (stretch) | prompt + N panels | rank inputs | `panel_order` permutations, balanced |

---

## 4. Data model (PostgreSQL)

Schema-first: judge/pipeline tables exist from M1 even though they're exercised from M7.

```
templates       (id, name, version, description, kind: builtin|custom,
                 schema jsonb, created_at)         -- immutable per version
projects        (id, name, description, template_id, template_version,
                 guidelines_md,                     -- annotator instructions (markdown)
                 labels_per_unit,                   -- "overlap": valid labels per unit (§6.4)
                 max_labels_per_unit,               -- ceiling for dynamic overlap growth (§6.4)
                 agreement jsonb,                   -- per-key consensus policy (§6.4)
                 gold_ratio, lease_minutes, min_reputation,
                 pipeline jsonb,                    -- routing policy stages (§7.2)
                 config jsonb, created_at)
batches         (id, project_id, name, source_filename,
                 unit_count, rejected_count, created_at)   -- one per bulk upload
units           (id, project_id, batch_id, payload jsonb,
                 priority int default 0,            -- assignment order (§6.4)
                 is_gold, gold_expected jsonb,
                 status: pending|in_progress|labeled|finalized)
slots           (id, unit_id, variant jsonb,
                 status: open|leased|filled|voided,
                 leased_by, lease_expires_at)
labels          (id, slot_id, annotator_id, raw jsonb, value jsonb,
                 confidence, reasoning,
                 latency_ms, tokens_in, tokens_out, cost_usd, cache_hit,
                 comment, submitted_at, is_valid)
final_labels    (id, unit_id, value jsonb, confidence,
                 method: auto_consensus|human_approved|human_override|expert,
                 provenance jsonb,                  -- contributing labels, weights, stage trace
                 decided_by, created_at)
users           (id, email, role: admin|reviewer|annotator,
                 api_key_hash, created_at)          -- access control, not labeling
annotators      (id, kind: human|model, display_name, email,
                 user_id,                           -- FK to users; null for kind=model
                 judge_config_id,                   -- null for humans
                 reputation_score, status, created_at)
judge_configs   (id, name, provider, model_id, params jsonb,
                 prompt_template, prompt_version,   -- immutable per version; edits bump version
                 budget jsonb,                      -- caps: $/project, $/day, max tokens
                 created_at)
reputation_events (id, annotator_id, kind: gold_pass|gold_fail|agreement|bias_flag|speed_flag,
                 delta, detail jsonb, created_at)
webhooks        (id, event: budget.cap_reached|gold.accuracy_dropped|
                     review.queue_backlog|project.completed,
                 target_url, secret, project_id,    -- null project_id = instance-wide
                 status, created_at)
```

Key constraints:
- `CHECK` that `labels_per_unit % n_variant_values = 0` (validated at project creation against the template).
- Unique partial index preventing two valid labels by the same annotator on the same *unit* (not just slot).
- Slot leasing uses `SELECT ... FOR UPDATE SKIP LOCKED` so concurrent annotators — human or judge worker — never collide.
- Unit payloads validated against the template schema at ingest; rejects listed row-by-row.
- Judge label caching keyed on `(judge_config_id + prompt_version, unit_id, variant)` — identical calls are never paid for twice.
- `annotators.user_id` required when `kind=human`; the linked user's `role` gates which API endpoints that annotator's token can call (§5). `kind=model` annotators authenticate as a `role=annotator` service user tied to the judge worker.

---

## 5. API surface (FastAPI)

```
GET    /templates                          list gallery (builtin + custom)
POST   /templates                          create custom template (JSON, validated)
POST   /templates/{id}:clone               copy any template into an editable draft (§2.5)
PUT    /templates/{id}                     edit draft/custom (schema changes bump version)
POST   /templates/{id}/preview             render-check a sample unit payload
POST   /projects                           create project (template, guidelines, overlap,
                                           agreement policy, pipeline)
POST   /projects/{id}/units:bulk           bulk-load units (JSONL: payload, priority,
                                           gold fields) → creates a batch, returns
                                           per-row validation report
POST   /projects/{id}/pairs:generate       side-by-side helper: build units from items
GET    /projects/{id}/units                browse/filter units (status, batch, priority,
                                           agreement, gold) + per-unit label detail
PATCH  /units/{id}                         adjust priority; void/requeue
POST   /projects/{id}/units:reprioritize   bulk priority update (by batch or filter)
GET    /tasks/next?annotator=...           assignment engine (humans and judge workers)
POST   /tasks/{slot_id}/submit             submit label (validated, canonicalized)
POST   /tasks/{slot_id}/skip               release lease

POST   /judges                             create judge config (provider, model, prompt, budget)
POST   /projects/{id}/judges/{jid}:attach  enroll a judge as an annotator on a project
POST   /projects/{id}/judges:run           orchestrator: run enrolled judges over open slots
GET    /projects/{id}/review               human approval queue (escalated units)
POST   /units/{id}/finalize                approve / override merged label

GET    /projects/{id}/progress             status funnel, per-batch and per-variant fill,
                                           per-key consensus rates, pipeline stage counts,
                                           throughput (labels/hr) + ETA at current rate
GET    /projects/{id}/analytics/agreement  kappa, per-unit entropy (humans vs judges vs both)
GET    /projects/{id}/analytics/bias       variant-bias metrics — humans AND judges (§9)
GET    /projects/{id}/analytics/costs      judge spend, cache hit rate, $/label
GET    /projects/{id}/active-learning/batch  next most-informative units (§8)
GET    /projects/{id}/export?format=...    JSONL export (§10)
GET    /annotators/{id}/report             reputation/calibration history, gold accuracy, bias

POST   /webhooks                           register a webhook (event type, target URL, secret)
GET    /webhooks                           list registered webhooks
DELETE /webhooks/{id}                      remove a webhook
```

Auth: API-key per `user`, role-gated (`admin` / `reviewer` / `annotator`) — `admin` covers templates/projects/judges/webhooks; `reviewer` covers `/projects/{id}/review` and `/units/{id}/finalize`; `annotator` covers `/tasks/*` (including judge workers, which authenticate as a `role=annotator` service user). Document the upgrade path to OAuth; don't build it. Every flow is scriptable — the docs show curl + a thin Python client for solo-builder automation.

---

## 6. Quality-control subsystem (template- and annotator-kind-agnostic)

### 6.1 Gold questions
- Golds are units with `gold_expected` (canonical answer, per input id; may grade a subset of inputs), injected at `gold_ratio` (default 10%), indistinguishable in the UI *and in judge prompts*, variant-balanced like everything else.
- Rolling gold accuracy per annotator; below-threshold pauses assignment and voids recent labels (slots reopen, balance preserved). For judges this catches prompt regressions and provider model drift automatically.

### 6.2 Reputation = calibration
Composite in [0, 1], recomputed on each `reputation_event`: gold accuracy (dominant), peer agreement on completed units, variant-bias penalty (where applicable), speed flags (humans only). Projects set `min_reputation`; the assignment engine filters on it. A judge's reputation is its calibration score and doubles as its **merge weight** (§7.1).

### 6.3 Agreement metrics
- Cohen's kappa (K=2) / Fleiss' kappa (K>2) on canonical values, per input field — computed within humans, within judges, and human-vs-judge (the last one is the interesting research artifact).
- Per-unit vote entropy separates genuinely ambiguous units from noisy raters — and drives escalation (§7.2) and active learning (§8).

### 6.4 Overlap, consensus & prioritization

- **Overlap** = `labels_per_unit` (K): how many valid labels each unit collects. Set per project; must satisfy variant divisibility (§2.7). This is the redundancy knob — K=1 for cheap pre-labeling passes, K=3–5 for quality-critical sets.
- **Per-key agreement policy** (`projects.agreement`): each input key declares how its votes are compared and what consensus is required:

  ```jsonc
  "agreement": {
    "category":      { "match": "exact",    "min_consensus": 0.67 },
    "fluency":       { "match": "within",   "tolerance": 1 },       // likert ±1 counts as agreeing
    "quality_flags": { "match": "jaccard",  "threshold": 0.5 }
  }
  ```

- **Dynamic overlap growth:** when a unit's K labels are in and any key misses `min_consensus`, the system can open additional slots (variant-balanced, up to `max_labels_per_unit`) instead of — or before — escalating to review. Policy per project: `on_disagreement: escalate | grow_then_escalate`.
- **Prioritization:** every unit carries an integer `priority` (set at upload, editable later, bulk-adjustable). The assignment engine orders open slots by `priority DESC, unit created_at ASC` *within* the balance constraints — urgent batches drain first without breaking counterbalancing. Golds inject independently of priority so high-priority bursts stay quality-checked.

---

## 7. Model judges & ensembles (M7–M8)

### 7.1 Built-in orchestrator
- MiniLP calls LLM APIs directly via a provider abstraction (Anthropic, OpenAI, OpenAI-compatible/local endpoints; one class per provider, ~small contract). The OpenAI-compatible/local class is what lets a fine-tuned checkpoint from the M9 active-learning loop get re-enrolled as a judge — same provider class, new `base_url`, no new code.
- A **judge config** = provider + model + params + versioned prompt template + budget caps. Enrolling a judge on a project creates a `kind=model` annotator; the orchestrator then drives the *same* `next`/`submit` loop humans use — leasing, golds, variant balance, and the annotator-unit exclusion all apply for free.
- Prompt assembly: project guidelines + template serialization (§2.1) + unit payload + strict answer-format instructions; responses parsed and canonicalized like any raw answer, with confidence elicited (or logprob-derived where the provider exposes it) and the reasoning trace stored.
- Operational guardrails: retries with backoff, rate limits, per-project/day budget caps (hard-stop + alert), response caching (§4), dry-run mode (estimate cost before running).

### 7.2 Merge & routing pipeline
Projects define an ordered routing policy (stored in `projects.pipeline`); the default ships as:

```jsonc
"pipeline": [
  { "stage": "ensemble",  "judges": ["gpt-x-judge", "claude-judge", "local-ft-v2"],
    "merge": "calibration_weighted" },              // weights = live reputation
  { "stage": "auto_finalize", "if": "consensus >= 0.9 && entropy <= 0.3" },
  { "stage": "human_review",  "else": true }        // escalate disagreement to humans
]
```

- **Calibration-weighted merge:** votes weighted by each judge's rolling reputation; produces a proposed `final_label` with confidence and full provenance (who voted what, at which weight, in which variant).
- **Escalate on disagreement:** high-consensus units auto-finalize; low-agreement / low-confidence units route to the **human review queue** — a fast accept/override UI showing the merged proposal, per-judge votes, and reasoning traces. Human decisions write `final_labels` with `method: human_approved | human_override`.
- Stages are declarative and composable (e.g. add an `expert_review` stage gated on a reviewer role, or run humans first and judges as tie-breakers). Arbitrary stage types are the extension point.

### 7.3 Webhooks & notifications
No new trigger logic — webhooks fire off checks that already exist in §6–§7: `budget.cap_reached` (7.1 budget caps), `gold.accuracy_dropped` (6.1 rolling gold accuracy), `review.queue_backlog` (7.2 escalation depth), `project.completed` (all units finalized). Registered per project or instance-wide (`webhooks`, §4). Payload carries event type, project/annotator id, and the triggering metric; delivery is fire-and-forget with retry-with-backoff, HMAC-signed with a per-webhook secret. This is what makes an unattended judge run (§7.1 dry-run → live) safe to leave running — budget and drift alerts don't require polling the dashboard.

---

## 8. Active-learning loop (M9)

"You train, MiniLP loops": training runs in the user's own stack; MiniLP owns selection, export, and re-enrollment.

1. **Select:** `GET /active-learning/batch` ranks unlabeled/unfinalized units by informativeness — ensemble disagreement, entropy, low confidence of the *current student model* (enrolled as a judge), optional embedding-diversity de-duping.
2. **Label:** the selected batch flows through the normal pipeline (judges → escalation → humans).
3. **Export:** training-set export of `final_labels` in FT-ready formats (§10).
4. **Re-enroll:** the user fine-tunes externally, then registers the new checkpoint as a judge config version (`local-ft-v3`). Its gold accuracy and agreement-vs-final-labels become the eval curve — the dashboard plots student-model calibration across iterations.
5. Repeat. Loop metrics (spend, human minutes, model-vs-human agreement per iteration) live on the dashboard.

---

## 9. Bias analytics (variant-bearing templates)

- **Global variant-preference rate:** e.g. `P(raw side = left)` ≈ 0.5 expected; binomial CI — reported separately for humans and judges (LLM order bias is a headline metric).
- **Per-annotator bias score:** each rater's/judge's variant-rate with CI; feeds reputation.
- **Per-unit order sensitivity:** does the canonical winner flip across variants? Flag high-flip units for extra labels or expert review.
- **Bias-adjusted outcomes:** win rates raw and stratified by variant.

---

## 10. Export formats

- **Preference JSONL** (RLHF-ready, side-by-side projects): `{prompt, chosen, rejected, meta:{votes_a, votes_b, ties, order_flip_rate, mean_annotator_reputation, human_reviewed}}`
- **SFT JSONL:** `{input, output}` built from finalized labels for generation-style templates.
- **Generic labels JSONL** (all projects): one row per unit with payload, `final_label`, and per-label provenance (annotator kind, reputation, variant, confidence, cost).
- **Raw labels JSONL:** one row per label with full raw/canonical/variant/judge provenance — the format researchers want for bias studies.
- Optional: Hugging Face `datasets`-compatible loading script.

---

## 11. Frontend (React + TS)

- **Annotation view:** template-driven renderer honoring the template's layout/render options (§2.2), hotkey engine with badges + `?` overlay (§2.4), **collapsible guidelines panel** (expanded on first task, `g` toggles), progress bar, skip, session stats, light/dark theme. Never shows model names, variant values, or A/B identity. Visual bar: modern card-based surfaces and crisp type — but every interaction is instant; throughput beats decoration.
- **Review queue (M8):** escalated units with merged proposal, per-judge votes + reasoning traces, one-key approve/override — throughput-optimized like the annotation view.
- **Widget registry:** one React component per display/input type, each declaring its hotkey behavior and render options — the frontend half of the extensibility contract (§2.6).
- **Template editor:** clone-from-gallery or from-scratch; validated JSON editor with autocomplete beside a live preview (layout, hotkeys, overlay all live) — §2.5.
- **Admin — new project wizard:** pick/clone template → guidelines editor (markdown + preview) → unit upload (JSONL drop, per-row validation report, batch naming, priority column) → overlap K / agreement policy / gold ratio / thresholds → pipeline editor (M8).
- **Progress view (per project):** status funnel (pending → in progress → labeled → finalized); per-batch progress bars; per-variant fill (paired bars — visual proof of counterbalancing); per-key consensus rates with drill-down to disagreeing units; throughput and ETA; unit browser (filter by status/batch/priority/agreement/gold) opening a per-unit detail drawer: payload preview, each label with annotator kind + reputation + variant, agreement state, escalation history.
- **Admin dashboard:** progress summary across projects, agreement and bias charts (split human/judge), judge cost panel, annotator table with reputation, AL iteration curves (M9).

---

## 12. Milestones

### 12.0 Execution notes (for coding agents — Sonnet/Opus, read first)

- **One milestone per session; land it green.** Each milestone below lists *Deliverables* (what files/modules exist afterward) and *Acceptance* (tests that must pass). Do not start a milestone until the previous one's acceptance suite is green in CI.
- **Layout conventions:** backend code in `backend/app/{api,models,services,schemas}/`; one service package per domain (`templates/`, `assignment/`, `quality/`, `judges/`, `merge/`, `analytics/`); Pydantic schemas mirror API payloads; every service function unit-tested in `backend/tests/` (mirror the package path). Frontend views in `frontend/src/views/`, widgets in `frontend/src/widgets/` (one file per display/input type), API client in `frontend/src/api/`.
- **Database:** every schema change is an Alembic migration; never edit an applied migration. Tests run against Postgres via docker compose (`pytest` uses a `TEST_DATABASE_URL`), not SQLite — `SKIP LOCKED` and partial indexes must be tested on the real engine.
- **Template engine invariants** (assert everywhere, they are the product): (1) slot counts per variant value are exactly K/n at creation and at completion; (2) an annotator never labels the same unit twice; (3) presentation-only template edits never bump versions, schema edits always do; (4) hotkey conflicts fail validation at save time.
- **When in doubt, check §2 (templates), §6.4 (overlap/priority), §7.2 (routing) — they are the spec.** DESIGN.md gets a decision-log entry whenever an implementation deviates from this plan.

**M0 — Scaffold: ✅ done.** Monorepo layout, Ruff + pytest + GitHub Actions CI, pre-commit, README skeleton with architecture diagram.

**M1 — Template engine + full data model.**
*Deliverables:* SQLAlchemy models + Alembic migrations for *all* of §4 (incl. `users.role`, `annotators.kind`, `judge_configs`, `final_labels`, `projects.pipeline`, `batches`, `webhooks` — schema-first, some unused until M7/M10); template JSON-schema validation incl. layout/render/hotkey rules (§2.1–§2.4); clone + versioning endpoints (§2.5); gallery seed data (all §3 templates); `units:bulk` ingest with batch creation, per-row validation report, priority column; slot pre-generation with variant balance.
*Acceptance:* slot counts exactly K/n per variant value for every unit; malformed payload rows rejected with row numbers, valid rows ingested; duplicate/reserved hotkeys fail template save; clone of a builtin is editable, original untouched; schema edit bumps version, layout edit doesn't; every gallery template round-trips validate → preview.

**M2 — Assignment engine.**
*Deliverables:* leasing with `SELECT … FOR UPDATE SKIP LOCKED`; lease-expiry sweeper; annotator-unit exclusion; gold injection at `gold_ratio`; skip/void → slot reopening with variant retained; priority-ordered assignment (`priority DESC, created_at ASC` within balance constraints, §6.4); role-gated API auth (admin/reviewer/annotator, §5).
*Acceptance:* concurrency test with N simulated annotators proving no double-assignment and preserved variant balance under abandonment — a README highlight; high-priority batch drains first without breaking per-variant balance; role-gating test proving an annotator token can't hit admin/reviewer endpoints.

**M3 — Annotation UI.**
*Deliverables:* template renderer honoring layout arrangements + per-block render options (§2.2); widget registry (all v1 display/input types); hotkey engine — auto-assignment, overrides, badges, `?` overlay, reserved keys, single-input auto-submit (§2.4); collapsible guidelines panel; `next`/`submit`/`skip` wiring; session stats; light/dark theme.
*Acceptance:* each gallery template renders and submits end-to-end (Playwright); every gallery task completable with keyboard only — zero mouse events; hotkey overlay shows the correct key for every interactive element.

**M4 — Quality subsystem.**
*Deliverables:* gold grading (per-key expected-answer matching using §6.4 match rules); reputation engine + events; agreement metrics (kappa per key, per-unit entropy); consensus evaluation with dynamic overlap growth (`grow_then_escalate`, §6.4); assignment gating on `min_reputation`.
*Acceptance:* below-threshold gold accuracy pauses an annotator and voids/reopens their recent slots with balance preserved; a planted disagreeing unit grows to `max_labels_per_unit` then escalates; kappa matches hand-computed fixtures.

**M5 — Analytics + progress UX + admin.**
*Deliverables:* progress endpoint (funnel, per-batch, per-variant, per-key consensus, throughput/ETA); progress view + unit browser + per-unit detail drawer (§11); §9 bias metrics with CIs; agreement/label-distribution analytics; admin dashboard; new-project wizard (clone/scratch template step, guidelines, upload with validation report, overlap/agreement/gold config).
*Acceptance:* progress numbers reconcile exactly with DB state under a seeded scenario (counts, consensus rates, ETA formula); unit browser filters compose; wizard creates a working project end-to-end from a JSONL fixture.

**M6 — Export, docs, demo (human-MVP release):** JSONL exports (§10), `docs/DESIGN.md` decision log, `docs/extending.md`, seeded demo (two sample projects: side-by-side + image classification), README GIF. *Acceptance: `docker compose up` → annotate the demo in <2 min; export re-imports cleanly.*

**M7 — Judge orchestrator:** provider abstraction (Anthropic, OpenAI, OpenAI-compatible/local endpoints), judge configs + versioned prompts, prompt assembly from templates, confidence/reasoning capture, retries/rate limits/budget caps/caching/dry-run, judges enrolled as annotators through the standard assignment loop, `budget.cap_reached` / `gold.accuracy_dropped` webhook events (§7.3). *Tests: a mock-provider judge fills slots respecting balance and golds; cache prevents duplicate spend; budget cap hard-stops and fires its webhook.*

**M8 — Ensembles + routing:** calibration-weighted merge, declarative pipeline stages, auto-finalize thresholds, human review queue UI (reviewer-role gated), `final_labels` provenance, `review.queue_backlog` / `project.completed` webhook events. *Tests: synthetic judges with known accuracies → merge weights converge; disagreement routes to review; overrides recorded; backlog webhook fires past threshold.*

**M9 — Active-learning loop:** informativeness ranking (disagreement/entropy/confidence), batch selection API, FT-ready exports, checkpoint re-enrollment as judge version (via the OpenAI-compatible/local provider class), iteration dashboard. *Demo: scripted loop with a toy student model improving over 3 iterations.*

**M10 — Marketplace:** export a template or judge-config as a shareable JSON bundle; import re-runs the same validation path units already go through (§2.1); a local directory of shared bundles ships with the repo — no hosted registry in v1. *Tests: exported bundle re-imports and round-trips validate → preview, same guarantee as gallery templates (M1).*

---

## 13. Repo layout

```
MiniLP/
├── backend/
│   ├── app/            # FastAPI app: api/, models/, services/
│   │                   #   templates/, assignment/, quality/, judges/ (orchestrator,
│   │                   #   providers/), merge/, active_learning/, analytics/,
│   │                   #   webhooks/, marketplace/, auth/ (roles)
│   ├── alembic/
│   └── tests/
├── frontend/
│   └── src/            # views: Annotate, Review, Admin (wizard, dashboard), Reports
│                       # widgets/ — display & input component registry
├── docs/
│   ├── DESIGN.md       # decision log — the "Principal engineer" artifact
│   ├── extending.md    # how to add display/input types (§2.6 contract)
│   └── architecture.md
├── docker-compose.yml
├── PLAN.md             # this file
└── README.md
```

## 14. Definition of done

**v1 (M6, human MVP):**
- `docker compose up` → working demo (two template types) in under 2 minutes
- CI green: unit + the concurrency/balance test suite
- README: problem statement, architecture diagram, GIF, bias-analytics screenshot
- `DESIGN.md` explaining *why* — template engine, counterbalancing, leasing

**v2 (M9):**
- Demo project labeled end-to-end by a 3-judge ensemble with human review of escalations
- Judge order-bias report (humans vs. models) — the blog-post centerpiece
- One scripted active-learning iteration runnable from the README
- Companion blog/LinkedIn post draft

**v3 (M10):**
- A project's template + judge configs export as a bundle and re-import into a fresh instance, validating and previewing identically
- Webhook fired and independently verified for at least one event type in a scripted demo

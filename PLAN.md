# MiniLP — Mini Labeling Platform

A self-hostable, open-source platform for collecting **any type of human label** through configurable **task templates** — with built-in quality controls: gold questions, inter-annotator agreement, rater reputation, and (for comparison-style templates) position-bias counterbalancing.

Side-by-side preference judging is the flagship *built-in template*, not the product. The product is the template engine.

**Target location:** `C:\my\agents\Projects\MiniLP`
**Stack:** FastAPI (Python ≥3.12) · PostgreSQL · React + TypeScript (Vite) · Docker Compose
**Timeline:** ~6 milestones, each sized for 1–2 focused sessions with Claude Code

---

## 1. Core design principles

1. **Templates define everything the annotator sees and returns.** A template = display blocks (what to show) + input fields (what to collect) + optional variant rules (how presentation is balanced). Adding a new labeling type means writing a template, not writing code.
2. **Store canonical data, present blinded data.** The database knows the ground truth about each unit (source models, expected answers, variant assignment). The annotator sees only what the template renders.
3. **Record raw and canonical answers.** For variant-balanced templates (e.g. side-by-side), every label stores both the raw input (side clicked) and the canonical value (item chosen) — this is what makes presentation bias measurable.
4. **Quality is a pipeline, not a report.** Gold questions, agreement, and bias scores feed a live rater reputation score that gates task assignment — uniformly across all template types.
5. **Guidelines are first-class.** Every project carries annotator instructions (markdown), always available in the annotation view as a collapsible panel — expanded on the annotator's first task, collapsed after, one keystroke to toggle.

---

## 2. Template system (the core)

### 2.1 Template schema

A template is a versioned JSON document:

```jsonc
{
  "name": "image-classification",
  "version": 1,
  "display": [                    // ordered blocks shown to the annotator
    { "type": "image", "source": "$unit.image_url" },
    { "type": "text",  "source": "$unit.context", "optional": true }
  ],
  "inputs": [                     // fields the annotator fills
    {
      "id": "category",
      "type": "radio",
      "label": "What is shown in the image?",
      "options": ["cat", "dog", "bird"],
      "allow_other": true         // renders an "Other…" option with free-text entry
    }
  ],
  "variants": null                // or a balancing spec, see §2.3
}
```

**Display block types (v1):** `text`, `markdown`, `image`, `audio`, `html_snippet` (sandboxed), `panel_group` (N side-by-side panels, contents drawn from unit payload per the active variant).

**Input field types (v1):** `radio` (with `allow_other`), `checkbox` (multi-select, with `allow_other`), `likert` (labeled scale), `free_text`, `choice_buttons` (large keyboard-mapped buttons, e.g. Left/Tie/Right), `span_select` (highlight spans in a text block — stretch goal, may slip to post-M6).

`$unit.<key>` resolves against the unit's JSON payload at render time. Template + payload validation happens at upload: every unit is checked against the template's required sources before it enters the pool.

### 2.2 Extensibility contract

Adding a new input or display type touches exactly three places, documented in `docs/extending.md`:
1. JSON-schema fragment for the type's config (backend validation),
2. a React component registered in the frontend widget registry,
3. an optional canonicalizer (raw answer → canonical value) on the backend.

Everything else — assignment, leasing, golds, agreement, reputation, export — is template-agnostic because it operates on JSON payloads and JSON answers.

### 2.3 Variants and counterbalancing (generalized from side-by-side)

Some templates present the same unit in multiple equivalent arrangements. A template may declare a **variant dimension**:

```jsonc
"variants": {
  "dimension": "panel_order",
  "values": ["AB", "BA"],
  "balance": "strict"   // slots pre-generated K/2 per value, K even (enforced)
}
```

Rules (unchanged from the original side-by-side spec, now applied to any variant-bearing template):
- `labels_per_unit = K` must be divisible by the number of variant values (default K=4 for 2 variants); slots are pre-generated with fixed variant values.
- **Across-annotator balancing:** an annotator never gets the same unit twice in any variant (repeats leak content memory).
- Slot assignment order is shuffled so sessions have no predictable variant rhythm.
- **Balance survives failures:** abandoned/expired/voided slots return to the pool *retaining their variant designation*. A unit is `complete` only when all K slots hold valid labels — guaranteeing exact balance at completion.
- Golds follow the same variant rules, so bias metrics on golds are comparable to real tasks.

Templates without variants (plain classification, rating) simply set `variants: null` and get one slot pool.

### 2.4 What gets stored per label

| Field | Meaning |
|---|---|
| `slot_id` | FK to the pre-generated slot (carries the variant value, if any) |
| `raw` | JSON: exactly what the annotator entered, per input id (e.g. `{"choice": "left"}`) |
| `value` | JSON: canonicalized answer (e.g. `{"choice": "A"}`); equals `raw` for variant-free templates |
| `latency_ms` | Time from render to submit (fast-click detection) |
| `annotator_id`, `submitted_at` | Attribution |

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

The user-described example maps directly to **Image classification**: show an image; collect a label from a radio group with preset labels, plus "Other" as an escape hatch for a manual label.

---

## 4. Data model (PostgreSQL)

```
templates       (id, name, version, description, kind: builtin|custom,
                 schema jsonb, created_at)     -- immutable per version; edits bump version
projects        (id, name, description, template_id,
                 guidelines_md,                 -- annotator instructions (markdown)
                 labels_per_unit, gold_ratio, lease_minutes, min_reputation,
                 config jsonb, created_at)
units           (id, project_id, payload jsonb,        -- resolved by template $unit.* refs
                 is_gold, gold_expected jsonb,          -- canonical expected answer(s)
                 status: pending|in_progress|complete)
slots           (id, unit_id, variant jsonb,            -- e.g. {"panel_order": "BA"} or null
                 status: open|leased|filled|voided,
                 leased_by, lease_expires_at)
labels          (id, slot_id, annotator_id, raw jsonb, value jsonb,
                 latency_ms, comment, submitted_at, is_valid)
annotators      (id, display_name, email, reputation_score, status, created_at)
reputation_events (id, annotator_id, kind: gold_pass|gold_fail|agreement|bias_flag|speed_flag,
                 delta, detail jsonb, created_at)
```

Key constraints:
- `CHECK` that `labels_per_unit % n_variant_values = 0` (validated at project creation against the template).
- Unique partial index preventing two valid labels by the same annotator on the same *unit* (not just slot).
- Slot leasing uses `SELECT ... FOR UPDATE SKIP LOCKED` so concurrent annotators never collide — the fun distributed-systems bit, worth a README section.
- Unit payloads validated against the template schema at ingest; rejects listed row-by-row.

---

## 5. API surface (FastAPI)

```
GET    /templates                          list gallery (builtin + custom)
POST   /templates                          create custom template (JSON, validated)
POST   /templates/{id}/preview             render-check a sample unit payload
POST   /projects                           create project (template_id or clone-from-template;
                                           validates K vs. variants, guidelines_md)
POST   /projects/{id}/units:bulk           bulk-load units (JSONL), payloads validated
POST   /projects/{id}/pairs:generate       side-by-side helper: build units from items
                                           (all-vs-all, round-robin by model, explicit)
GET    /tasks/next?annotator=...           assignment engine: reputation gate → gold
                                           injection → variant-balanced slot pick → lease;
                                           returns template + unit payload + guidelines
POST   /tasks/{slot_id}/submit             submit label (validates lease + inputs against
                                           template, canonicalizes raw → value)
POST   /tasks/{slot_id}/skip               release lease, slot returns to pool
GET    /projects/{id}/progress             completion; per-variant fill counts
GET    /projects/{id}/analytics/agreement  Cohen's/Fleiss' kappa, per-unit entropy
GET    /projects/{id}/analytics/bias       variant-bias metrics (§7) — variant templates only
GET    /projects/{id}/export?format=...    JSONL export (§8)
GET    /annotators/{id}/report             reputation history, gold accuracy, bias
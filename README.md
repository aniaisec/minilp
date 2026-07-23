# MiniLP — Mini Labeling Platform

A self-hostable, open-source platform for collecting **any type of human label** through configurable **task templates** — image classification, ratings, policy review, transcription checks, and side-by-side preference judging for RLHF/LLM evaluation — with quality controls built in from the start: gold questions, inter-annotator agreement, rater reputation, and position-bias counterbalancing for comparison tasks.

> **Status:** Milestone 5 (analytics + admin). See [PLAN.md](PLAN.md) for the full roadmap.

## Why

Label collection tools tend to be either rigid single-purpose UIs or heavyweight enterprise suites — and quality control is usually an afterthought. MiniLP treats both as first-class:

- **Templates, not code** — a template defines what the annotator sees (text, images, audio, side-by-side panels) and what they answer (radio with an "Other" escape hatch, checkboxes, Likert scales, choice buttons, free text). Start from a gallery of examples or from scratch; adding a whole new labeling type means writing a template, not a feature.
- **Guidelines built in** — every project carries markdown annotator instructions, rendered as a collapsible panel in the annotation view.
- **Counterbalanced presentation** — comparison templates pre-generate slots with fixed panel orders (exactly K/2 each); balance is enforced at assignment and preserved through skips, lease expiry, and voided labels.
- **Measurable bias** — every label records both the raw input (side clicked) and the canonical value (item chosen), unlocking left-preference rates, per-annotator bias scores, and per-unit order sensitivity.
- **Rater reputation** — gold questions, peer agreement, bias, and speed flags feed a live score that gates task assignment — uniformly across all template types.

## Architecture

```mermaid
flowchart LR
    subgraph Frontend["React + TS (Vite)"]
        AV["Annotation view\n(template renderer · guidelines)"]
        AD["Admin\n(wizard · gallery · dashboard)"]
    end

    subgraph Backend["FastAPI"]
        API[REST API]
        TPL["Template engine\n(schema · validation · variants)"]
        ASSIGN["Assignment engine\n(lease · gold injection · balance)"]
        QUAL["Quality pipeline\n(golds · agreement · reputation)"]
        ANALYTICS["Analytics\n(agreement · bias)"]
    end

    DB[(PostgreSQL)]

    AV -->|"next / submit / skip"| API
    AD -->|"templates / projects / reports"| API
    API --> TPL
    API --> ASSIGN
    API --> ANALYTICS
    TPL --> DB
    ASSIGN --> DB
    QUAL --> DB
    ANALYTICS --> DB
    ASSIGN -.->|"reputation gate"| QUAL
```

## Quickstart

```bash
docker compose up --build
```

- API: http://localhost:8000 (docs at `/docs`)
- Frontend: http://localhost:5173

### Local development

```bash
# Backend
cd backend
pip install -e ".[dev]"
uvicorn app.main:app --reload

# Tests run against a real PostgreSQL (SKIP LOCKED, partial indexes and the
# migrations themselves need it — the suite skips DB-backed tests rather than
# lying on SQLite). Point it at one and run:
docker compose up -d db
docker compose exec db psql -U minilp -c "CREATE DATABASE minilp_test;"   # first time only
export TEST_DATABASE_URL=postgresql+psycopg://minilp:minilp@localhost:5432/minilp_test
# PowerShell: $env:TEST_DATABASE_URL = "postgresql+psycopg://minilp:minilp@localhost:5432/minilp_test"
pytest && ruff check .
# On Linux/macOS with Python ≤ 3.12, `pip install -e ".[dev,localdb]"` auto-spawns
# a throwaway Postgres so TEST_DATABASE_URL isn't needed.

# Frontend
cd frontend
npm install
npm run dev            # dev server (proxies /api → backend)
npm run test           # vitest: renderer, hotkeys, canonicalization, admin formatting
npm run build          # typecheck + production build

# Hooks
pre-commit install
```

### Annotation UI (M3)

The annotation view is template-driven: it renders any gallery template's layout,
display blocks, and inputs, and drives the `next` / `submit` / `skip` loop. Open it
against a running backend with the project, annotator, and API key in the URL:

```
http://localhost:5173/?project=<id>&annotator=<id>&key=<api-key>
```

Every task is completable from the keyboard alone — number/letter/arrow keys judge,
`Enter` submits, `s` skips, `g` toggles guidelines, `d` toggles dark mode, `u` undoes
the last selection, and `?` opens the shortcut overlay. Key badges are drawn on every
option. Selecting an answer doesn't submit by itself; an opt-in **Auto-submit** toggle
(off by default) restores one-keystroke submission for single-choice templates.

### Quality subsystem (M4)

Every label that lands runs the same pipeline, whether a human or a model judge
submitted it:

1. **Canonicalized server-side** — the browser still computes `value`, but the
   backend recomputes it from `raw` + the slot's variant and stores its own answer.
   Gold grading, agreement and merge all read `value`, so a wrong client can't
   corrupt the quality signal.
2. **Graded against golds** — per input key, using the project's declared match
   rules (`exact` / `within` ± tolerance / `jaccard` ≥ threshold). A gold may
   grade a subset of the template's inputs.
3. **Scored** — a composite reputation in [0, 1]: rolling gold accuracy
   (dominant), peer agreement, a variant-bias penalty, and speed flags (humans
   only). A new annotator starts near 1.0 via a smoothing prior rather than at 0,
   so `min_reputation` gating doesn't lock out everyone who hasn't seen a gold yet.
4. **Enforced** — below-threshold gold accuracy pauses the annotator and voids
   their recent labels. Voided labels are kept as an audit trail; their slots
   reopen **retaining their variant**, so counterbalancing survives a suspension
   exactly as it survives a skip or a lease expiry.
5. **Reconciled** — once a unit has its K labels, per-key consensus is evaluated.
   Under `grow_then_escalate` a disagreeing unit opens another *balanced* round of
   slots (n at a time, never breaking K/n) up to `max_labels_per_unit`, then
   escalates to human review.

Analytics: Cohen's kappa (K=2) / Fleiss' kappa (K>2) per input key, plus per-unit
vote entropy — computed within humans, within judges, and human-vs-judge.

```
GET  /annotators/{id}/report                 reputation, gold accuracy, bias, event log
POST /annotators/{id}:resume                 lift a quality pause (admin)
GET  /projects/{id}/analytics/agreement      kappa + entropy per key
GET  /projects/{id}/consensus                per-unit consensus, escalation state
```

Golds stay invisible throughout: `GET /tasks/next` never exposes `is_gold`, and
the submit response reports only whether *you* were paused — never whether the
unit was a gold you got wrong, and never your peers' votes.

### Analytics + admin (M5)

Everything the quality pipeline records becomes legible. Progress reconciles
*exactly* with the database — the funnel, per-batch and per-variant fill, per-key
consensus rates and the throughput/ETA are each derived from one authoritative
query, never a stale cache:

```
GET  /tasks/available?annotator={id}         annotator landing: open labels per project
GET  /templates/{id}/sample                  example unit payload + required/optional fields
PUT  /templates/{id}/sample                  save an edited example (no version bump)
POST /projects/{id}/units:bulk  (format=json|tsv|jsonl)   upload units, per-row report
GET  /projects                               list projects (admin dashboard)
GET  /projects/{id}/progress                 funnel · per-batch · per-variant fill ·
                                             per-key consensus · throughput + ETA
GET  /projects/{id}/analytics/bias           §9 variant/order bias, humans vs judges
GET  /projects/{id}/analytics/distribution   canonical-answer distribution per key
GET  /projects/{id}/annotators               roster: reputation, gold accuracy, volume
GET  /projects/{id}/batches                  batches (unit-browser filter)
GET  /projects/{id}/units?status=&batch_id=&is_gold=&escalated=&min_priority=
                                             unit browser — filters compose
GET  /units/{id}                             per-unit drawer: each label with annotator
                                             kind + reputation + variant, consensus state
POST /projects/{id}/units:reprioritize       bulk priority by batch or status
```

**Bias is the research artifact (§9).** Variant-preference is reported with a
Wilson confidence interval and split *humans vs. judges* — LLM order bias is a
headline metric. Per-unit **order sensitivity** flags units whose canonical winner
flips between the AB and BA presentations, and per-annotator bias uses the same
score reputation already penalizes, so the dashboard and an annotator's report
never disagree.

**Counterbalancing, visible.** Per-variant fill renders as paired bars with a
`balanced` flag — equal totals per value *are* the K/n invariant (§2.7), so a
broken balance is a bar you can see rather than a number you have to trust.

**The admin surface** (React, `#/admin`) is a project dashboard, a tabbed
per-project view (progress · unit browser + detail drawer · bias/distribution ·
annotator roster), a **template gallery**, and a **new-project wizard**. Reviewer-
gated analytics stay behind the role check; the unit *list* is annotator-readable.

The **template gallery** (`#/admin/templates`) lists every template and renders a
*live, interactive preview* — the real annotation renderer, not a mock — driven by
per-template **sample data** you can edit and save. The saved sample is the example
the wizard prefills, so a project always starts from a payload shape that's known
to render.

The **wizard** clones a gallery template → guidelines → **unit upload** → overlap K
/ agreement / gold config. Upload accepts a **`.json`** array or a **`.tsv`** (header
+ one unit per row) file — pick the type and the wizard shows the exact example
format for that template, prefilled from its sample; paste directly or choose a
file. Required fields are verified (client-side warning, authoritative per-row
check on the server), and every row's outcome comes back in the validation report.

**Annotation UX.** Selecting an answer no longer submits on its own — you pick,
adjust if needed, then click **Submit** (or press Enter). Auto-submit-on-select is
an opt-in speed toggle that persists across sessions. The `allow_other` "Other…"
option now opens a free-text box on click (previously only the `o` hotkey did).

**Annotator landing page.** Opening the app with an annotator but no project
(`?annotator=<id>&key=<key>`) shows a table of every project with the number of
labels still needed — projects that need work sort to the top, most first —
counting exactly the open slots the assignment engine would still hand *that*
annotator (same unit-exclusion). Clicking a row drops straight into the labeling
loop for that project.

Open the admin surface, or the annotator landing, against a running backend:

```
http://localhost:5173/#/admin?key=<admin-api-key>
http://localhost:5173/?annotator=<id>&key=<api-key>          # landing → pick a task
http://localhost:5173/?project=<id>&annotator=<id>&key=<key>  # straight into one
```

## Roadmap

The full plan is in [PLAN.md](PLAN.md) (§12). Milestones land one at a time, each
green in CI before the next starts.

| Milestone | Scope | Status |
|---|---|---|
| M0 | Scaffold, CI, pre-commit, README | ✅ Done |
| M1 | Template engine, full data model, gallery seeds, slot pre-generation | ✅ Done |
| M2 | Assignment engine (`SKIP LOCKED` leasing, gold injection, balance under failure, role-gated auth) | ✅ Done |
| M3 | Annotation UI (template renderer, widget registry, hotkey engine, collapsible guidelines) | ✅ Done |
| M4 | Quality subsystem (golds, reputation, agreement, consensus growth) | ✅ Done |
| M5 | Analytics + admin (progress, bias analytics, unit browser, template gallery, project wizard, annotator landing) | ✅ Done |
| M6 | Export (JSONL formats), `docs/extending.md`, seeded demo, README GIF | ⬜ Not started |
| M7 | Judge orchestrator (provider abstraction, judge configs, prompts, budget caps, webhooks) | ⬜ Not started |
| M8 | Ensembles + routing (calibration-weighted merge, pipeline stages, review queue UI, `final_labels`) | ⬜ Not started |
| M9 | Active-learning loop (informativeness ranking, batch selection, FT-ready exports, iteration dashboard) | ⬜ Not started |
| M10 | Marketplace (export/import template + judge-config bundles) | ⬜ Not started |

**Where things stand:** the human-labeling core is complete end to end — define a
template, create a project, upload units (`.json`/`.tsv`), label from the keyboard
with quality controls, and watch progress, agreement and bias analytics in the
admin UI. Model judges, ensemble merge/routing, the active-learning loop, and the
shareable-bundle marketplace (M7–M10) are designed in PLAN.md but not yet built;
the data model has carried their tables since M1 (`judge_configs`, `final_labels`,
`webhooks`, `projects.pipeline`), so they slot in without migrations-of-migrations.

## Repo layout

```
MiniLP/
├── backend/          # FastAPI app: api/, models/, schemas/, services/
│                     #   services/: templates, assignment, quality, analytics, ingest, auth, slots
│                     #   alembic/ migrations · tests/ (pytest, run against real Postgres)
├── frontend/         # React + TS (Vite): annotation view, annotator landing, admin/ (dashboard,
│                     #   progress, unit browser, bias, template gallery, project wizard)
├── docs/             # DESIGN.md — decision log + postmortems ("why", not "what")
├── docker-compose.yml
├── Testing.txt       # manual test scripts, per milestone
├── PLAN.md           # full project plan (§1–§14)
└── README.md
```

## License

MIT (to be added).

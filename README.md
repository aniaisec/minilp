# MiniLP — Mini Labeling Platform

A self-hostable, open-source platform for collecting **any type of human label** through configurable **task templates** — image classification, ratings, policy review, transcription checks, and side-by-side preference judging for RLHF/LLM evaluation — with quality controls built in from the start: gold questions, inter-annotator agreement, rater reputation, and position-bias counterbalancing for comparison tasks.

> **Status:** Milestone 4 (quality subsystem). See [PLAN.md](PLAN.md) for the full roadmap.

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
pytest && ruff check .

# Frontend
cd frontend
npm install
npm run dev            # dev server (proxies /api → backend)
npm run test           # vitest: renderer, hotkeys, canonicalization
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
`Enter` submits (auto-submits when the template has a single required input), `s`
skips, `g` toggles guidelines, `d` toggles dark mode, `u` undoes the last selection,
and `?` opens the shortcut overlay. Key badges are drawn on every option.

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

## Roadmap

| Milestone | Scope | Status |
|---|---|---|
| M0 | Scaffold, CI, pre-commit, README | ✅ |
| M1 | Template engine, data model, gallery seeds, slot pre-generation | ✅ |
| M2 | Assignment engine (`SKIP LOCKED` leasing, balance under failure) | ✅ |
| M3 | Annotation UI (template renderer, widget registry, hotkey engine, collapsible guidelines) | ✅ |
| M4 | Quality subsystem (golds, reputation, agreement, consensus growth) | ✅ |
| M5 | Analytics + admin (project wizard, template gallery) | ⬜ |
| M6 | Export, docs, seeded demo | ⬜ |

## Repo layout

```
MiniLP/
├── backend/          # FastAPI app: api/, models/, services/
├── frontend/         # React + TS: Annotate, Admin, Reports views
├── docs/             # DESIGN.md (decision log), architecture notes
├── docker-compose.yml
└── PLAN.md           # full project plan
```

## License

MIT (to be added).

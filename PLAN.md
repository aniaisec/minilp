# MiniLP — Mini Labeling Platform

A self-hostable, open-source platform for collecting pairwise (side-by-side) preference judgments for RLHF and LLM evaluation, with built-in quality controls: **position-bias counterbalancing**, gold questions, inter-annotator agreement, and rater reputation.

**Target location:** `C:\my\agents\Projects\MiniLP`
**Stack:** FastAPI (Python 3.12) · PostgreSQL · React + TypeScript (Vite) · Docker Compose
**Timeline:** ~6 milestones, each sized for 1–2 focused sessions with Claude Code

---

## 1. Core design principles

1. **Counterbalanced presentation is a scheduling problem, not a UI trick.** Randomizing order per render is not enough — it doesn't guarantee balance. MiniLP pre-generates *judgment slots* with fixed presentation orders and enforces balance at assignment time.
2. **Store canonical data, present blinded data.** The database always knows which response is A and which is B (and which model produced each). The annotator only ever sees "Left" and "Right."
3. **Every judgment records both the canonical choice and the raw side clicked.** This is what makes position-bias measurable after the fact.
4. **Quality is a pipeline, not a report.** Gold questions, agreement, and position-bias scores feed a live rater reputation score that gates task assignment.

---

## 2. Side-by-side counterbalancing spec (your requirement, formalized)

### 2.1 Rules

- Each comparison pair `(A, B)` is configured with `judgments_per_pair = K`, where **K must be even** (enforced at project creation; default `K = 4`).
- The system pre-generates `K` **judgment slots** per pair:
  - `K/2` slots with `presentation_order = AB` (A shown on the left)
  - `K/2` slots with `presentation_order = BA` (B shown on the left)
- **Across-annotator counterbalancing:** a given annotator is never assigned the same pair twice, in either order. (Showing the same annotator both orders leaks — they remember the content — so balance is achieved across the annotator pool, which is the standard design.)
- Slot assignment order is shuffled so an annotator's session isn't a predictable AB/BA rhythm.
- **Balance survives failures:** if a slot is abandoned, expired (lease timeout), or its judgment is voided (e.g., annotator later disqualified), the slot returns to the pool *retaining its order designation*. A pair is only `complete` when all K slots are filled by valid judgments — guaranteeing exactly K/2 valid judgments per order at completion.
- Gold questions (§5.1) follow the same counterbalancing rules, so bias metrics on golds are comparable to bias metrics on real tasks.

### 2.2 What gets stored per judgment

| Field | Meaning |
|---|---|
| `slot_id` | FK to the pre-generated slot (carries `presentation_order`) |
| `selected_side` | `left` / `right` / `tie` — the raw click |
| `selected_item` | `A` / `B` / `tie` — derived canonically from side + order |
| `latency_ms` | Time from render to submit (fast-click detection) |
| `annotator_id`, `submitted_at` | Attribution |

### 2.3 Analytics this unlocks (Milestone 5)

- **Global left-preference rate:** `P(selected_side = left)` — should be ≈ 0.5 if content, not position, drives choices. Report with a binomial confidence interval.
- **Per-annotator position-bias score:** each rater's left-rate with CI; feeds reputation.
- **Per-pair order sensitivity:** does the winner flip between AB and BA presentations of the same pair? Flag high-flip pairs as *position-sensitive* (often genuinely close-quality pairs) and optionally route them for extra judgments or expert review.
- **Bias-adjusted win rates:** report model win rates both raw and stratified by presentation order.

---

## 3. Data model (PostgreSQL)

```
projects        (id, name, description, judgments_per_pair, gold_ratio,
                 lease_minutes, min_reputation, created_at)
items           (id, project_id, source_model, prompt_text, response_text, meta jsonb)
pairs           (id, project_id, item_a_id, item_b_id, is_gold, gold_expected,  -- 'A'|'B'
                 status: pending|in_progress|complete)
judgment_slots  (id, pair_id, presentation_order: 'AB'|'BA',
                 status: open|leased|filled|voided,
                 leased_by, lease_expires_at)
judgments       (id, slot_id, annotator_id, selected_side, selected_item,
                 latency_ms, comment, submitted_at, is_valid)
annotators      (id, display_name, email, reputation_score, status, created_at)
reputation_events (id, annotator_id, kind: gold_pass|gold_fail|agreement|bias_flag|speed_flag,
                 delta, detail jsonb, created_at)
```

Key constraints:
- `CHECK` that `judgments_per_pair % 2 = 0` at the project level.
- Unique partial index preventing two valid judgments by the same annotator on the same *pair* (not just slot).
- Slot leasing uses `SELECT ... FOR UPDATE SKIP LOCKED` so concurrent annotators never collide — this is the fun distributed-systems bit and worth a section in the README.

---

## 4. API surface (FastAPI)

```
POST   /projects                          create project (validates even K)
POST   /projects/{id}/items:bulk          bulk-load responses (JSONL upload)
POST   /projects/{id}/pairs:generate      pair generation strategies: all-vs-all,
                                          round-robin by model, or explicit pairs
GET    /tasks/next?annotator=...          assignment engine: lease next slot
                                          (reputation gate → gold injection →
                                           balanced slot pick → lease)
POST   /tasks/{slot_id}/submit            submit judgment (validates lease, records
                                          side + canonical choice)
POST   /tasks/{slot_id}/skip              release lease, slot returns to pool
GET    /projects/{id}/progress            completion, per-order fill counts
GET    /projects/{id}/analytics/bias      §2.3 metrics
GET    /projects/{id}/analytics/agreement Cohen's/Fleiss' kappa, per-pair entropy
GET    /projects/{id}/export?format=...   JSONL export (§6)
GET    /annotators/{id}/report            reputation history, gold accuracy, bias score
```

Auth: simple API-key + annotator token for v1 (document the upgrade path to OAuth; don't build it).

---

## 5. Quality-control subsystem

### 5.1 Gold questions
- Golds are pairs with a known correct answer, injected at `gold_ratio` (default 10%) — indistinguishable from real tasks in the UI, and counterbalanced like everything else.
- Rolling gold accuracy per annotator; below-threshold accuracy pauses assignment and voids recent judgments (slots reopen, balance preserved).

### 5.2 Reputation score
Composite score in [0, 1], recomputed on each `reputation_event`:
- Gold accuracy (dominant weight)
- Agreement with peers on completed pairs
- Position-bias penalty (left-rate CI excludes 0.5 by a margin)
- Speed flags (latency below a per-project floor)

Projects set `min_reputation`; the assignment engine filters on it.

### 5.3 Agreement metrics
- Cohen's kappa for K=2 designs, Fleiss' kappa for K>2.
- Per-pair vote entropy to surface genuinely ambiguous pairs vs. noisy raters.

---

## 6. Export formats

- **Preference JSONL** (RLHF-ready): `{prompt, chosen, rejected, meta:{votes_a, votes_b, ties, order_flip_rate, mean_annotator_reputation}}`
- **Raw judgments JSONL**: one row per judgment with full side/order provenance — the format researchers want for bias studies.
- Optional: Hugging Face `datasets`-compatible loading script.

---

## 7. Frontend (React + TS)

- **Annotation view:** prompt at top, two blinded response panels, `Left / Tie / Right` buttons + keyboard shortcuts (`←`, `↓`, `→`), progress bar, skip. No model names, no A/B labels, ever.
- **Admin dashboard:** project setup, JSONL upload, progress by presentation order (two bars per pair batch — a nice visual proof of the counterbalancing feature), bias and agreement charts, annotator table with reputation.
- Deliberately plain, fast, keyboard-first — annotation UIs live or die on throughput.

---

## 8. Milestones

**M0 — Scaffold (½ session):** monorepo layout (`backend/`, `frontend/`, `docker-compose.yml`), Ruff + pytest + GitHub Actions CI, pre-commit hooks, README skeleton with architecture diagram.

**M1 — Data model + core API:** SQLAlchemy models + Alembic migrations, project/item/pair endpoints, pair generation strategies, slot pre-generation with even-K validation. *Tests: slot counts are exactly K/2 per order for every pair.*

**M2 — Assignment engine:** leasing with `SKIP LOCKED`, lease expiry sweeper, annotator-pair exclusion, gold injection, skip/void → slot reopening. *Tests: concurrency test with N simulated annotators proving no double-assignment and preserved order balance under abandonment; this test is a README highlight.*

**M3 — Annotation UI:** the annotation view wired to `next`/`submit`, keyboard flow, session stats.

**M4 — Quality subsystem:** golds, reputation engine, agreement metrics, assignment gating.

**M5 — Bias analytics + admin dashboard:** §2.3 metrics with CIs, charts, per-pair flip inspection.

**M6 — Export, docs, demo:** JSONL exports, `DESIGN.md` (decision log — counterbalancing rationale, leasing design, reputation weighting), seeded demo mode (`docker compose up` loads a sample project with synthetic annotators), short screen-capture GIF in the README.

---

## 9. Repo layout

```
MiniLP/
├── backend/
│   ├── app/            # FastAPI app: api/, models/, services/ (assignment, quality, analytics)
│   ├── alembic/
│   └── tests/
├── frontend/
│   └── src/            # views: Annotate, Admin, Reports
├── docs/
│   ├── DESIGN.md       # decision log — the "Principal engineer" artifact
│   └── architecture.md
├── docker-compose.yml
├── PLAN.md             # this file
└── README.md
```

## 10. Definition of done (portfolio bar)

- `docker compose up` → working demo in under 2 minutes
- CI green: unit + the concurrency/balance test suite
- README: problem statement, architecture diagram, GIF, bias-analytics screenshot
- `DESIGN.md` explaining *why* — especially the counterbalancing and leasing designs
- Companion blog/LinkedIn post draft

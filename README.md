# MiniLP — Mini Labeling Platform

A self-hostable, open-source platform for collecting **any type of human label** through configurable **task templates** — image classification, ratings, policy review, transcription checks, and side-by-side preference judging for RLHF/LLM evaluation — with quality controls built in from the start: gold questions, inter-annotator agreement, rater reputation, and position-bias counterbalancing for comparison tasks.

> **Status:** Milestone 10 — **the marketplace**, and with it every milestone in
> PLAN.md's roadmap is done. The human-MVP (M0–M6) is complete, LLM judges label
> through the same assignment loop humans use (M7), their votes merge into a
> single decided label — auto-finalized when decisive, escalated to a human
> review queue when not (M8) — a checkpoint can be re-enrolled as the next judge
> version, ranked against the next most-informative batch, and tracked on an
> eval curve as it (hopefully) improves (M9), and now a template, judge config,
> or whole project starter kit exports as a shareable, credential-free JSON
> bundle that re-imports into a fresh instance and validates and previews
> identically (M10). See [PLAN.md](PLAN.md) for the full roadmap.

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
        HOME["Annotator home\n(table · cards · exit-to-home)"]
        AV["Annotation view\n(template renderer · guidelines)"]
        RQ["Review queue\n(proposal · votes · traces)"]
        AD["Admin\n(wizard · gallery · dashboard)"]
    end

    subgraph Backend["FastAPI"]
        API[REST API]
        TPL["Template engine\n(schema · validation · variants)"]
        ASSIGN["Assignment engine\n(lease · gold injection · balance)"]
        QUAL["Quality pipeline\n(golds · agreement · reputation)"]
        JUDGE["Judge orchestrator\n(prompt · cache · budget)"]
        MERGE["Merge & routing\n(weighted merge · stages · final_labels)"]
        ANALYTICS["Analytics\n(agreement · bias · cost)"]
        HOOKS["Webhooks\n(signed · retried · logged)"]
    end

    DB[(PostgreSQL)]
    LLM["LLM providers\nAnthropic · OpenAI · local"]

    HOME -->|"available work"| API
    AV -->|"next / submit / skip"| API
    RQ -->|"queue / approve / override"| API
    AD -->|"templates / projects / judges / reports"| API
    API --> TPL
    API --> ASSIGN
    API --> ANALYTICS
    API --> JUDGE
    API --> MERGE
    JUDGE -->|"the same next / submit loop"| ASSIGN
    JUDGE <-->|"prompt / answer"| LLM
    QUAL -->|"once a unit stops collecting"| MERGE
    TPL --> DB
    ASSIGN --> DB
    QUAL --> DB
    MERGE --> DB
    ANALYTICS --> DB
    HOOKS --> DB
    ASSIGN -.->|"reputation gate"| QUAL
    MERGE -.->|"merge weight = reputation"| QUAL
    JUDGE -.->|"budget.cap_reached"| HOOKS
    QUAL -.->|"gold.accuracy_dropped"| HOOKS
    MERGE -.->|"review.queue_backlog · project.completed"| HOOKS
```

Two edges carry the design. The judge orchestrator has no privileged path into the
database: it reaches work through the assignment engine, exactly as the annotation
view does — the whole M7 design. And merge & routing is the *tail of the quality
pipeline*, not a service beside it: it runs when a unit stops collecting, weights
each vote by the reputation §6.2 already maintains, and never touches slots.

## Quickstart

```bash
docker compose up --build
```

- API: http://localhost:8000 (docs at `/docs`)
- Frontend: http://localhost:5173

The backend migrates, seeds the template gallery and **bootstraps a demo** on
start-up, so there is nothing else to run. The container log prints ready-to-open
URLs — annotator links for each demo project, and the admin surface:

```
http://localhost:5173/?project=1&annotator=1&key=dev-admin-key   # start labeling
http://localhost:5173/#/admin?key=dev-admin-key                  # admin
http://localhost:5173/#/admin/templates/new?key=dev-admin-key    # visual builder
```

Set `MINILP_BOOTSTRAP_DEMO=0` in `docker-compose.yml` for a clean install (the
gallery is still seeded; the demo projects are not).

> Full operational instructions — build, test, reset the database, start each
> piece, and what to do when one of them misbehaves — are in
> **[docs/RUNBOOK.md](docs/RUNBOOK.md)** (PowerShell, with bash equivalents).

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
npm run test           # vitest: renderer, hotkeys, canonicalization, admin formatting, judges
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

### Authoring + export (M6)

**A visual template builder.** `#/admin/templates/new` opens a palette of display
blocks and input fields you drag onto a canvas, reorder by dragging (or with
Alt+↑/↓ on a focused row — the builder is keyboard-drivable like everything else),
and edit inline: label, options, `allow_other`, `required`, per-option hotkeys,
per-block render options. In the **right-hand column** runs the **real annotation
renderer** on a generated sample — it sticks as you scroll, so the thing you are
building stays on screen the whole time you build it. Narrow the window and the
preview moves below the editor; the rule is pure CSS (a media query for the split,
a container query for the editor's own columns), so there is nothing to resize by
hand and no state to get out of step with the window.

The builder and the JSON editor are **two views of one document**, not two
formats — switching between them never loses work, because the JSON view is a
serialization of the same schema the canvas manipulates. Validation runs live
(hotkey conflicts, missing options, bad bounds) and again on the server, which
stays authoritative.

**Ten new field types** land through the §2.6 extensibility contract:

| Type | Value shape | Notes |
|---|---|---|
| `number` | number | bounded numeric entry |
| `slider` | number | continuous scale with a live read-out |
| `rating` | int | stars — a `likert` skin, keys `1..N` |
| `boolean` | bool | two-button toggle, so "no" ≠ "unanswered" |
| `select` / `multiselect` | string / string[] | dropdowns for long option lists |
| `tags` | string[] | free-form, folded to lower case and de-duplicated |
| `ranking` | string[] (**ordered**) | drag to order; defaults to `ordered` matching |
| `date` / `datetime` | ISO string | native pickers, sortable as stored |

Dropdowns and rankings deliberately get **no per-option hotkeys** — they exist for
lists long enough that per-option keys would exhaust the budget and collide with
everything else on the page (§2.4).

**One editor, three entry points (§2.5).** The same builder creates a template,
edits a template (versioning rules apply: presentation-only edits update in place,
schema edits bump), and edits a live project's configuration. Editing a project's
schema **clones the template and rebinds** the project to the copy, so a template
shared with other projects is never reshaped underneath them.

**Grow a project without recreating it.** The `Configure` tab edits guidelines, K,
agreement policy, gold ratio and thresholds; raising K opens another *balanced*
round of slots on every unfinished unit, and lowering it past collected work is
refused rather than silently discarding labels. The `Add tasks` tab appends a batch
through the same upload surface (JSON/TSV/paste, per-row validation report) — with
a gold affordance, because **a gold in an appended batch enters measurement
immediately**: `is_gold` + `gold_expected` is all it takes, and golds stay
indistinguishable in the UI.

**Exports (§10).** Four JSONL formats from the `Export` tab or the API:

```
GET /projects/{id}/export?format=labels       one row per unit: payload, final label, provenance
GET /projects/{id}/export?format=raw          one row per label: raw + canonical + variant + rater
GET /projects/{id}/export?format=preference   RLHF pairs {prompt, chosen, rejected, meta}
GET /projects/{id}/export?format=sft          {input, output} from a free-text answer
GET /templates/{id}                           the schema the builder reads and writes
PUT /templates/{id}                           save an edit (server applies the versioning rules)
PATCH /projects/{id}                          edit config; a new template_schema clones-and-rebinds
```

The `labels` export **re-imports through `units:bulk` unchanged** — payload,
`is_gold`, `gold_expected` and `priority` sit exactly where ingest looks for them,
so an export is also a backup. `raw` keeps voided labels, flagged: a bias study
needs to know a rater was removed, not to have their rows vanish.

**Deleting a template.** The gallery's Delete button appears only on custom
templates and only when nothing depends on the template existing — a template is
the definition of every label collected under it. Builtins are refused (clone
instead, same rule that makes them immutable to edit), and an in-use version is
refused with the **blocking projects named**, read from
`GET /templates/{id}/usage` *before* the click rather than discovered as a 409
after it. `?versions=all` removes a whole lineage, all-or-nothing, so history is
never left with holes in it.

```
DELETE /templates/{id}                        delete one version (admin)
DELETE /templates/{id}?versions=all           delete every version of that name
GET    /templates/{id}/usage                  which projects block a delete, and why
```

Adding your own field or block type: [`docs/extending.md`](docs/extending.md) —
four places, and nothing else.

### Model judges (M7)

**A judge is an annotator.** Enrolling one creates a `kind=model` annotator, and
from that moment the orchestrator drives the *same* `next`/`submit` loop humans
use. Leasing, gold injection, variant balance, the annotator-unit exclusion,
server-side canonicalization, gold grading, reputation and consensus growth all
apply with no judge-specific branch anywhere in them. The entire M7 backend adds
one package (`services/judges/`) and three tables; nothing in M1–M6 changed to
accommodate it.

That is not a tidiness argument, it is what buys the headline number. A judge is
shown the panels **in its slot's variant order**, named by position ("Left" /
"Right") exactly as a human sees them, and answers positionally. The raw answer
keeps the side, the canonical value keeps the item — so **LLM order bias falls out
of the same `/analytics/bias` endpoint that measures human order bias**, with
confidence intervals, per judge. Serializing the panels as "A" and "B" would have
made every judge look perfectly unbiased by construction.

**Four providers, one small contract.** `mock`, `anthropic`, `openai`, and
`openai_compatible` — each a thin `httpx` call, no vendor SDKs. The
OpenAI-compatible class is the one that matters later: a local vLLM/llama.cpp
server, or a fine-tuned checkpoint from the M9 loop, is that same class with a
different `base_url` and no new code. API keys are **never stored** — a config
names an environment variable the server reads at call time, so a judge config
stays shareable (M10 bundles) without carrying credentials.

The `mock` provider ships in `app/`, not `tests/`: it is deterministic (answers
hash from the prompt), free, and offline, which is what lets the demo show the
whole judge loop with no key and lets the acceptance suite assert on *what* a
judge answered.

**Guardrails, because unattended runs spend money.**

```
POST /judges                                 create a config (provider, model, prompt, caps)
POST /judges/{id}:version                    next prompt version — immutable per version (§4)
POST /projects/{id}/judges/{jid}:attach      enrol as a kind=model annotator
POST /projects/{id}/judges:run               run — or price it first with {"dry_run": true}
GET  /projects/{id}/judges                   enrolled judges + live spend against caps
GET  /projects/{id}/judge-runs               run history: estimates and live runs together
GET  /projects/{id}/analytics/costs          $/label, cache-hit rate, judge vs human volume
POST /webhooks · GET /webhooks/deliveries    alerts + the delivery log (§7.3)
```

- **Dry run** assembles the real prompts, prices them, and releases every slot —
  you find out a run costs $40 before it costs $40. Estimates and live runs sit
  side by side in the history, which is the only honest way to check the estimate.
- **Response cache** keyed on `(judge_config + prompt_version, unit, variant)`, so
  identical calls are never paid for twice. Variant is *in* the key on purpose:
  answering "BA" from "AB"'s cache would fabricate perfect order-consistency and
  quietly destroy the bias metric, while looking like a saving. The assembled
  prompt's hash is checked too — a cache that answers from a prompt nobody sent is
  not a cache.
- **Budget caps** (`project_usd`, `daily_usd`, `max_tokens`, `max_labels`) are
  checked before *and* after every call and hard-stop the run. Spend is read back
  from the `labels` table rather than a counter, so a cap survives a restart. An
  unknown budget key is rejected at save time — a typo'd cap that silently does
  nothing is precisely the failure caps exist to prevent.
- **Unknown model prices report as `unpriced`, never `$0.00`.** A budget computed
  from a price nobody knows is not a budget.
- **Failures leave no trace but a report line.** A provider outage or an
  unparseable reply releases the lease, so the unit returns to the pool with its
  variant intact. A judge whose output we could not read never becomes a label.
- **Webhooks** (`budget.cap_reached`, `gold.accuracy_dropped`) add no new trigger
  logic — they fire off checks §6–§7 already run. Deliveries are HMAC-signed over
  the exact bytes sent, retried with backoff, and **recorded**: a webhook that has
  been quietly 404ing for a week otherwise looks identical to one that never
  needed to fire.

The `Judges` tab on any project does all of it — enrol, price, run, and watch
spend against the cap — with the alert config underneath, where §7.3 argues it
belongs.

**Try it yourself, from the admin.** Every project card carries **Label this →**,
each project header a **Start labeling →**, and the nav a **Label tasks →** for
the whole queue. They resolve the caller's rater record on click — `users` and
`annotators` are separate by design (§4), so an admin holding a user token
previously had no way to find their own annotator id short of querying the
database:

```
GET  /me                    the token holder, and their annotator id (null if none)
POST /me:annotator          get — or create on first use — their rater record
```

`GET` never creates: a page load must not insert rows. `POST` is get-or-create
and returns 200 rather than 201, because a user with two rater records would
split their own reputation and could label the same unit twice. The admin labels
**as themselves** — not a preview mode: the labels count, carry their name in the
roster, and are graded against golds like anyone else's.

### Ensembles, routing and the review queue (M8)

M7 got many raters to vote. M8 turns those votes into **one decided label**, and
decides who decides.

**The merge weight is the reputation.** §6.2 ends by saying a judge's calibration
score doubles as its merge weight, and that is implemented literally: there is no
second scoring system. Anything that moves reputation — gold accuracy, peer
agreement, variant bias — moves merge weight in the same breath. Two synthetic
judges of known accuracy (6/8 and 2/8 on a project of golds) separate cleanly, and
on a 1–1 tie the calibrated one decides. Below §6.1's pause threshold a judge is
removed rather than down-weighted: down-weighting is for the merely mediocre.

**Routing is a document, not a code path.** A project's `pipeline` is an ordered
list of stages, and the one that ships is §7.2's own:

```jsonc
[ { "stage": "ensemble",      "merge": "calibration_weighted" },
  { "stage": "auto_finalize", "if": "consensus >= 0.9 && entropy <= 0.3" },
  { "stage": "human_review",  "else": true } ]
```

Stages are a registry, so `register_stage("expert_review", …)` plus a name in a
project's pipeline is the whole extension — no fork. Conditions are parsed by a
~120-line grammar rather than `eval`: a pipeline arrives from the network, and
`__import__('os')` is not a routing rule. **Unknown variables are errors, not
silent falses** — a rule that quietly never fires is the worst possible failure
mode, so `consensuss >= 0.9` is a 422 on the project edit, not three thousand
units piling up in review with nothing to point at.

**Consensus is the worst key, not the average.** A unit is only as decided as its
least-decided input, and entropy is computed over *match-rule buckets* rather than
distinct values — so a likert key declared `within ±1` treats votes of 4 and 5 as
one answer everywhere, instead of agreeing in §6.4 and escalating in §7.2.

**An override stays explainable.** `final_labels` keeps one row per unit with the
provenance §7.2 asks for — who voted what, at which weight, in which variant — and
a human override records the proposal it *rejected*. A year later you can see what
the ensemble said, what the human said instead, and which judges were wrong.

```
GET  /review/queue?project=            escalated units + merged proposal + every vote
GET  /review/{unit_id}                 one item plus its template (renders real widgets)
POST /review/{unit_id}:decide          {"decision": "approve" | "override", "value": …}
GET  /review/depth                     queue depth and the backlog threshold
GET  /projects/{id}/pipeline           the routing policy, resolved (default when unset)
PUT  /projects/{id}/pipeline           replace it — validated at save time
POST /projects/{id}/route              re-run routing over already-collected units
```

The review queue is reviewer-role gated and built for throughput like the
annotation view: `a` approves, `o` overrides, `n`/`p` walk the queue, and deciding
advances. Per-judge reasoning traces sit inline — a reviewer who has to open a
second view to find out *why* the ensemble proposed something will stop looking.

Two lifecycle consequences worth stating, because both were found by the existing
suite rather than reasoned about afterwards:

- **Voiding evidence unwinds an automatic decision.** An auto-finalized unit whose
  labels are later voided returns to collecting and its `final_labels` row goes —
  otherwise a decision survives the disappearance of everything it was made from.
  A *human* decision is not unwound: a reviewer's verdict is not evidence that can
  be withdrawn by discrediting the raters underneath it.
- **`POST /route` is safe to press twice.** Re-running never re-decides a unit a
  human decided, and writes one `final_labels` row however often it runs.

`project.completed` and `review.queue_backlog` (§7.3) fire from the ordinary
submit path with no new trigger logic: the backlog event fires on the escalation
that *crosses* the threshold, and again if a drained queue re-forms — a backlog
that came back is news. Completion is announced once.

### Annotator home and exit-to-home (M8)

The M5 landing page became a place you can **return to**, at a stable route
(`?annotator=&key=` with no project). It has two presentations of one list — a
dense table and a card grid with fill bars — toggled and remembered like the theme
and auto-submit preferences. **Both render from a single `/tasks/available`
fetch**, which is the endpoint that already applies the assignment engine's own
exclusion, so the cards and the rows can never disagree with each other or with
what the annotator will actually be served. Toggling the view does not re-ask the
server.

The empty state distinguishes *"nothing exists yet"* from *"you have labeled
everything available"* — different situations for the person reading them.

Every project screen carries a visible way back: the annotation view, the review
queue, and the per-project admin view. **Leaving releases the held lease** through
the same `skip` path the `s` key uses, so the slot reopens immediately with its
variant retained (§2.7) instead of sitting leased until it expires; an unsubmitted
answer prompts first, a submitted one never blocks the exit, and a failed release
never traps you on the page — the lease expires on its own, and being stuck in a
project is worse.

`Esc` was the natural key and was already reserved for "clear selection" (§2.4),
so exit took **`x`** — and `x` was *added to the reserved set* on both sides of the
wire rather than merely hoped to be free. Auto-assignment can no longer reach for
it, and a template that asks for it fails validation at save time, which is what
§2.4 promises about hotkey collisions.

### Active-learning loop (M9)

"You train, MiniLP loops" (§8): fine-tuning happens in your own stack, and M9
owns exactly three things — what to label next, re-enrolling the checkpoint
you trained, and whether it actually got better.

**No new schema, on purpose.** Batch selection reads the consensus rate and
vote entropy §6.4 already computes; re-enrolling a checkpoint is `POST
/judges/{id}:version` followed by `:attach` — the same two calls the Judges
tab already makes — wrapped in one call; the eval curve reads gold accuracy
(§6.2) and `final_labels` (§7.2). A judge config's `prompt_version` **is** the
loop's iteration counter, reused rather than duplicated — `local-ft` re-enrolled
three times is iterations 1, 2, 3, with no second number to keep in sync.

```
GET  /projects/{id}/active-learning/batch                next most-informative units (§8)
POST /projects/{id}/active-learning/checkpoints:register  version + attach in one call
GET  /projects/{id}/active-learning/iterations?name=      the eval curve across versions
```

- **Informativeness is a weighted mean, not three separate thresholds.**
  Ensemble disagreement (1 − the worst key's consensus rate), vote entropy, and
  — when you pass the judge whose confidence should count — that judge's own
  reported confidence, averaged over whichever of the three a unit actually
  has. A brand-new unit with no votes yet and no judge confidence scores at a
  neutral 0.5 rather than 0.0: nothing indicates it's *easy*, so nothing claims
  it is. A unit already in `final_labels` is dropped from the pool entirely —
  there's nothing left to be informative about.
- **`agreement_vs_final` is the metric peer agreement can't be.** §6.2's
  `peer_agreement` compares a rater to the peer majority and has no idea a
  human later overrode the ensemble (§7.2). The eval curve reads
  `final_labels.value` directly, so a checkpoint's score reflects what was
  actually decided — override included.
- **The generic-labels export now prefers the decided row.** An export taken
  after a human review used to still show the ensemble's rejected proposal,
  because it recomputed a "final label" from live consensus instead of reading
  `final_labels`. It now reads the decided row first and falls back to
  consensus only for a unit still collecting votes — a training-set export
  should never bake in the ensemble's mistake over the human's correction.
- **Optional embedding-diversity de-duping.** Point `dedupe_field` at a payload
  key holding a numeric vector and the batch greedily drops a unit too similar
  (cosine ≥ `dedupe_threshold`) to a higher-scored one already kept — informative
  and *different*, not eight near-duplicates of the same hard case.

The **Active learning** tab on any project shows the eval curve for a
checkpoint line, a form to register the next one, and a live preview of the
next ranked batch — the whole loop from one screen.

**Try it without training anything.** The seeded demo ships a toy student
model, `demo-student`, already re-enrolled three times with a pinned (and
improving) answer against a fixed six-gold mix — gold accuracy 1/6 → 2/6 → 3/6,
exactly like `docs/DESIGN.md`'s M8 disagreement demo pins its judges' answers
instead of hoping for them:

```
curl -H "Authorization: Bearer $KEY" \
  'localhost:8000/projects/7/active-learning/iterations?name=demo-student' | python -m json.tool
```

### Marketplace (M10)

"A local directory of shared bundles ships with the repo — no hosted registry in
v1" (PLAN.md §12). M10 adds no tables: templates, judge configs and projects have
carried everything a bundle needs since M1, so a bundle is a *view* over rows that
already exist, not a new persistence layer.

```
GET  /templates/{id}:export             a template as a shareable bundle
GET  /judges/{id}:export                a judge config as a shareable bundle
GET  /projects/{id}:export-bundle       template + enrolled judges + config, not units/labels
GET  /marketplace/bundles               the shipped local directory's metadata
GET  /marketplace/bundles/{filename}    one shipped bundle's full JSON
POST /marketplace/bundles/{filename}:import   import a shipped bundle by filename
POST /marketplace/import                import a pasted/uploaded bundle
```

- **Import reuses the exact validation path units already go through.** `POST
  /marketplace/import` calls the same `create_template` / `create_judge_config` /
  `create_project` a hand-authored `POST /templates` / `POST /judges` / `POST
  /projects` call makes — an imported bundle gets no special trust, and gets the
  same guarantee a gallery template gets at boot (M1 acceptance: validate ->
  preview).
- **Never a credential.** A judge config only ever stores `params.api_key_env` —
  the *name* of an environment variable the server reads at call time — so a
  judge-config bundle is shareable exactly as exported; there is nowhere a secret
  could have been.
- **A project bundle is a starter kit, not a backup.** It carries the template,
  the enrolled judge configs, and the project's non-data config (guidelines,
  overlap, gold ratio, routing pipeline). Units and labels stay behind — `GET
  /projects/{id}/export` (§10) is the tool for a project's *data*. Importing one
  creates a new template + new judge configs + (by default) a new live project
  bound to them, with the judges attached — "re-import into a fresh instance"
  meaning a working project, not orphaned config rows.
- **Name collisions are handled differently for templates and judge configs, on
  purpose.** `templates` is unique on `(name, version)`, so an imported template
  colliding with an existing name is renamed (`"… (imported)"`) rather than
  refused. `judge_configs` has no such constraint — versioning already mirrors
  templates there (§2.5), so importing a same-named judge config simply writes
  the next version, exactly like `POST /judges/{id}:version` would.
- **The Marketplace admin page** (`#/admin/marketplace`) lists the shipped local
  bundles with one-click import, accepts a pasted or uploaded bundle from
  anywhere, and lists every template and judge config with a "Download bundle"
  button. A project's bundle downloads from that project's **Export** tab, next
  to the JSONL formats.

Three bundles ship in `backend/app/services/marketplace/bundles/`: a template
(`summarization-quality` — not in the built-in gallery), a judge config
(`calibrated-mock-judge` — a deterministic mock judge, no API key needed), and a
project starter kit (`toxicity-triage` — template + judge + a routing pipeline
that auto-finalizes clear cases and escalates the rest).

## Verifying it by hand

The automated suites are the contract (`pytest` + `vitest`, both green in CI).
This section is for driving the thing yourself — every step below is something
you can watch happen.

### 0. Bring it up

```bash
docker compose up --build
```

Wait for `=== MiniLP demo ready ===` in the backend log. It prints an admin key
(`dev-admin-key`), an annotator id, and a URL for every surface. Everything below
assumes `KEY=dev-admin-key`, annotator `1`, and the demo's project numbering on a
clean database — **project 6 is "Demo — Ensemble + review queue"**, built for M8:
two model judges that always disagree, K = max_K = 2 so there is no room to grow,
and `min_consensus: 0.9` so nothing can auto-finalize. **Project 7 is "Demo —
Active-learning loop"**, built for M9: a toy student model, `demo-student`,
already re-enrolled three times against fresh six-gold batches, with gold
accuracy climbing 1/6 → 2/6 → 3/6 by construction. If your ids differ, take them
from the log rather than from here.

Running the two halves separately instead:

```bash
# Backend — http://localhost:8000, docs at /docs
cd backend
pip install -e ".[dev]"
docker compose up -d db
export MINILP_DATABASE_URL=postgresql+psycopg://minilp:minilp@localhost:5432/minilp
alembic upgrade head
MINILP_BOOTSTRAP_DEMO=1 uvicorn app.main:app --reload

# Frontend — http://localhost:5173, proxies /api → :8000
cd frontend
npm install
npm run dev
```

### 1. Run the automated suites

```bash
# Backend (needs a real PostgreSQL — see "Local development" above)
cd backend
export TEST_DATABASE_URL=postgresql+psycopg://minilp:minilp@localhost:5432/minilp_test
pytest                      # 557 tests
pytest tests/test_active_learning.py tests/test_active_learning_api.py tests/test_bootstrap_demo.py -v   # M9 only
pytest tests/test_marketplace.py tests/test_marketplace_api.py -v   # M10 only, 36 tests
ruff check .

# Frontend
cd frontend
npm run test                # 246 tests
npm run test -- src/views/admin/ActiveLearningPanel.test.tsx   # M9 only
npm run test -- src/views/admin/MarketplacePanel.test.tsx src/views/admin/ExportPanel.test.tsx   # M10 only
npm run build               # typecheck + production build
```

### 2. Backend by hand — merge, routing, review

```bash
KEY=dev-admin-key
AUTH="Authorization: Bearer $KEY"
JSON="Content-Type: application/json"
API=localhost:8000
```

**a. See the routing policy a project is running.** Unset means the shipped
default (§7.2); `stages` and `variables` are the vocabulary a pipeline may use.

```bash
curl -s -H "$AUTH" $API/projects/6/pipeline | python -m json.tool
# is_default: true · stages: ensemble → auto_finalize → human_review
```

**b. Prove a bad policy is refused at save time**, not silently ignored:

```bash
curl -s -X PUT -H "$AUTH" -H "$JSON" \
  -d '{"pipeline":[{"stage":"auto_finalize","if":"consensuss >= 0.9"}]}' \
  $API/projects/6/pipeline
# → 422  pipeline[0]: unknown variable 'consensuss' (available: confidence, consensus, …)

curl -s -X PUT -H "$AUTH" -H "$JSON" \
  -d '{"pipeline":[{"stage":"teleport"}]}' $API/projects/6/pipeline
# → 422  pipeline[0]: unknown stage 'teleport' (known: [auto_finalize, ensemble, human_review])
```

**c. Subscribe to the M8 events before anything happens**, so you can watch them
fire off checks that already run rather than off new trigger logic:

```bash
curl -s -X POST -H "$AUTH" -H "$JSON" \
  -d '{"event":"review.queue_backlog","target_url":"https://example.test/hook","project_id":6}' $API/webhooks
curl -s -X POST -H "$AUTH" -H "$JSON" \
  -d '{"event":"project.completed","target_url":"https://example.test/done","project_id":6}' $API/webhooks
```

**d. Run the two disagreeing judges and watch routing send every unit to review:**

```bash
curl -s -X POST -H "$AUTH" -H "$JSON" -d '{}' $API/projects/6/judges:run | python -m json.tool
# → labels_written: 16 (8 units × 2 judges), runs: 2

curl -s -H "$AUTH" $API/projects/6/progress | python -c \
  "import sys,json;print(json.load(sys.stdin)['funnel'])"
# → {'pending': 0, 'in_progress': 0, 'labeled': 8, 'finalized': 0, 'escalated': 8, 'total': 8}

curl -s -H "$AUTH" "$API/review/queue?project=6&limit=3" | python -m json.tool
```

Each item carries the merged proposal *and* every vote behind it. The interesting
number is the weighting: the golds on this project expect `cat`, so
`demo-judge-cat` has earned reputation ≈ 1.00 and `demo-judge-dog` ≈ 0.30, and the
merge proposes **`cat` at ≈ 0.77 consensus** — a weighted win, not a coin flip,
and still short of the 0.9 needed to auto-finalize. That is calibration-weighted
merge doing something a majority vote could not.

**e. Check the backlog webhook fired on the crossing, not on every escalation:**

```bash
curl -s -H "$AUTH" "$API/webhooks/deliveries?project=6" | python -m json.tool
# → one review.queue_backlog delivery, metric {"queue_depth": 5, "threshold": 5}
```

Deliveries are recorded whether or not they succeed (`example.test` will fail, and
the row records the error) — a hook that has been quietly 404ing for a week
otherwise looks identical to one that never needed to fire.

**f. Decide one, and check the provenance survives.**

```bash
UNIT=$(curl -s -H "$AUTH" "$API/review/queue?project=6&limit=1" | python -c \
  "import sys,json;print(json.load(sys.stdin)['items'][0]['unit_id'])")

curl -s -X POST -H "$AUTH" -H "$JSON" \
  -d '{"decision":"override","value":{"category":"bird"},"comment":"both judges misread it"}' \
  $API/review/$UNIT:decide | python -m json.tool
# → method: human_override, queue_depth drops by one

curl -s -H "$AUTH" $API/review/$UNIT | python -m json.tool
# final_label.method == "human_override"; provenance.proposal keeps what you rejected
```

Approving instead takes the proposal as it stands:

```bash
NEXT=$(curl -s -H "$AUTH" "$API/review/queue?project=6&limit=1" | python -c \
  "import sys,json;print(json.load(sys.stdin)['items'][0]['unit_id'])")
curl -s -X POST -H "$AUTH" -H "$JSON" -d '{"decision":"approve"}' $API/review/$NEXT:decide
# → method: human_approved, value {"category": "cat"}, confidence 0.769…
```

**g. Prove a human decision is not undone by a later automatic pass:**

```bash
curl -s -X POST -H "$AUTH" -H "$JSON" -d '{"include_finalized":true}' $API/projects/6/route
# → {"units_considered": 8, "auto_finalized": 0, "escalated": 6, "skipped": 2}
#   the 2 skipped are the ones you decided; press it as often as you like
curl -s -H "$AUTH" $API/review/$UNIT | grep -o '"method": "[a-z_]*"'   # still human_override
```

**h. Drain the queue and watch `project.completed` fire once:**

```bash
while UNIT=$(curl -s -H "$AUTH" "$API/review/queue?project=6&limit=1" | python -c \
  "import sys,json;d=json.load(sys.stdin);print(d['items'][0]['unit_id'] if d['items'] else '')") \
  && [ -n "$UNIT" ]; do
  curl -s -o /dev/null -X POST -H "$AUTH" -H "$JSON" -d '{"decision":"approve"}' $API/review/$UNIT:decide
done

curl -s -H "$AUTH" $API/projects/6/progress | python -c \
  "import sys,json;print(json.load(sys.stdin)['funnel'])"        # → finalized: 8
curl -s -H "$AUTH" "$API/webhooks/deliveries?project=6" | grep -c project.completed   # → 1
```

**i. Role gating.** The queue is reviewer-gated; an annotator token is refused:

```bash
curl -s -o /dev/null -w "annotator → %{http_code}\n" \
  -H "Authorization: Bearer some-annotator-key" $API/review/queue    # → 403
curl -s -o /dev/null -w "admin → %{http_code}\n" -H "$AUTH" $API/review/queue  # → 200
```

Editing the policy and re-running routing stay **admin**-only, because both change
what happens to every future unit:

```bash
curl -s -o /dev/null -w "reviewer PUT pipeline → %{http_code}\n" \
  -X PUT -H "Authorization: Bearer some-reviewer-key" -H "$JSON" \
  -d '{"pipeline":null}' $API/projects/6/pipeline                    # → 403
```

### 3. Backend by hand — active-learning loop

Project 7 ("Demo — Active-learning loop") already has three checkpoints run at
boot, so the eval curve is populated from the first request.

**a. See the eval curve — gold accuracy climbing by construction:**

```bash
curl -s -H "$AUTH" "$API/projects/7/active-learning/iterations?name=demo-student" \
  | python -m json.tool
# → iterations[0].gold_accuracy.rate ≈ 0.1667 (1/6)
#   iterations[1].gold_accuracy.rate ≈ 0.3333 (2/6)
#   iterations[2].gold_accuracy.rate == 0.5    (3/6)
```

**b. Rank the next batch.** With nothing labeled since boot, project 7's demo
units are already finalized (K=1, single-vote auto-finalize), so point this at
a project with open disagreement instead — project 6, still mid-review from
step 2:

```bash
curl -s -H "$AUTH" "$API/projects/6/active-learning/batch?limit=5" | python -m json.tool
# → pool_size counts only unfinalized units; each carries disagreement/entropy
#   from its votes so far. A unit with zero votes yet would score 0.5 (neutral),
#   not 0.0 — nothing indicates it's *easy*.
```

**c. Register a fourth checkpoint — the "re-enroll" step (§8 step 4):**

```bash
curl -s -X POST -H "$AUTH" -H "$JSON" -d '{
  "name": "demo-student",
  "provider": "mock",
  "model_id": "ckpt-4",
  "params": {"mock": {"answers": {"category": "cat"}}}
}' $API/projects/7/active-learning/checkpoints:register | python -m json.tool
# → iteration: 4 — the SAME counter as prompt_version, not a second one
```

The curve already shows a fourth point (`label_count: 0` — the seeded demo's
three batches are already finalized, so there's nothing left for it to label
until you add a fresh batch through **Add tasks**, same as any other judge):

```bash
curl -s -H "$AUTH" "$API/projects/7/active-learning/iterations?name=demo-student" \
  | python -c "import sys,json;print(len(json.load(sys.stdin)['iterations']))"   # → 4
```

**d. Role gating.** Registering a checkpoint is admin-only; reading the curve
and the batch are reviewer-gated, same bucket as costs and progress:

```bash
curl -s -o /dev/null -w "reviewer register → %{http_code}\n" \
  -X POST -H "Authorization: Bearer some-reviewer-key" -H "$JSON" \
  -d '{"name":"x","provider":"mock","model_id":"m"}' \
  $API/projects/7/active-learning/checkpoints:register   # → 403
curl -s -o /dev/null -w "annotator read curve → %{http_code}\n" \
  -H "Authorization: Bearer some-annotator-key" \
  "$API/projects/7/active-learning/iterations?name=demo-student"   # → 403
```

**e. The FT-ready export now reads the decided row.** Override a unit in the
review queue (step 2f above), then export project 6 and check the export shows
what the human decided, not what the ensemble proposed:

```bash
curl -s -H "$AUTH" "$API/projects/6/export?format=labels" | python -c \
  "import sys,json;rows=[json.loads(l) for l in sys.stdin];\
r=[r for r in rows if r.get('final_method')=='human_override'][0];\
print(r['final_label'], r['final_method'])"
# → {'category': 'bird'}, human_override — the export shows the correction,
#   not the ensemble's rejected 'cat'/'dog' proposal
```

### 4. Backend by hand — marketplace bundles

**a. Export a builtin template and re-import it.** The imported copy is a new,
independent row — editing or deleting it never touches the original:

```bash
TID=$(curl -s -H "$AUTH" "$API/templates" | python -c \
  "import sys,json;print([t for t in json.load(sys.stdin) if t['name']=='image-classification'][0]['id'])")
curl -s -H "$AUTH" "$API/templates/$TID:export" | tee /tmp/template-bundle.json | python -m json.tool
NEW_ID=$(curl -s -X POST -H "$AUTH" -H "$JSON" \
  -d "{\"bundle\": $(cat /tmp/template-bundle.json)}" \
  "$API/marketplace/import" | python -c "import sys,json;print(json.load(sys.stdin)['template']['id'])")
# → previews identically to the original — the M1 gallery guarantee, extended:
curl -s -X POST -H "$AUTH" -H "$JSON" -d '{"payload":{"image_url":"http://x/cat.png"}}' \
  "$API/templates/$NEW_ID/preview" | python -c "import sys,json;print(json.load(sys.stdin)['payload_valid'])"
# → True
```

**b. A judge-config bundle never carries a credential.** Only the *name* of an
environment variable travels — grep the bundle for anything that looks like a key:

```bash
JID=$(curl -s -X POST -H "$AUTH" -H "$JSON" -d \
  '{"name":"demo-export-judge","provider":"anthropic","model_id":"claude-x","params":{"api_key_env":"ANTHROPIC_API_KEY"}}' \
  "$API/judges" | python -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -s -H "$AUTH" "$API/judges/$JID:export" | tee /tmp/judge-bundle.json | python -m json.tool
grep -i "sk-\|secret" /tmp/judge-bundle.json   # → no match
```

**c. The shipped local directory — a one-click starter kit.** `toxicity-triage`
bundles a template, a mock judge, and a routing pipeline into one importable
project:

```bash
curl -s -H "$AUTH" "$API/marketplace/bundles" | python -m json.tool
curl -s -X POST -H "$AUTH" "$API/marketplace/bundles/toxicity-triage.json:import" | python -m json.tool
# → a new template, a new judge config, and a new project with the judge
#   already attached — ready for units:bulk with no further setup
```

**d. Role gating.** Export and import are admin-only, the same bucket as
templates and judges:

```bash
curl -s -o /dev/null -w "reviewer export → %{http_code}\n" \
  -H "Authorization: Bearer some-reviewer-key" "$API/templates/$TID:export"   # → 403
curl -s -o /dev/null -w "reviewer import → %{http_code}\n" \
  -X POST -H "Authorization: Bearer some-reviewer-key" -H "$JSON" \
  -d "{\"bundle\": $(cat /tmp/template-bundle.json)}" "$API/marketplace/import"   # → 403
```

**e. A malformed bundle gets the real validation errors, not a 500.**

```bash
curl -s -X POST -H "$AUTH" -H "$JSON" -d \
  '{"bundle": {"bundle_version": 1, "kind": "template",
    "template": {"name": "bad", "inputs": [{"id": "x", "type": "radio", "options": ["only-one"]}]}}}' \
  "$API/marketplace/import" -w "\n%{http_code}\n"
# → 422, {"errors": ["input 'x' (radio) needs at least 2 options"]} — the exact
#   error POST /templates would give a hand-authored version of the same schema
```

### 5. Frontend by hand

Open the **annotator home** (this is the stable route to return to):

```
http://localhost:5173/?annotator=1&key=dev-admin-key
```

- Every project is listed with labels available, units open, and your own
  contribution. Click **Cards** — the same numbers, as a card grid with fill bars.
  Reload: the view you chose is still selected (it persists like the theme).
- Narrow the window to phone width: the grid collapses to one column.
- Compare a row's "labels needed" with `GET /tasks/available?annotator=1` — they
  are the same fetch, so they cannot disagree.
- A project you are blocked from shows *why* (paused, below `min_reputation`) with
  its button disabled, rather than a mysterious empty row.

**Exit-to-home, the part with a DB consequence.** Click into a project, then:

1. Note the `slot_id` in the network tab from `GET /tasks/next`.
2. Press **`x`** (or click **← Home (x)**).
3. Check the slot went back to the pool with its variant intact:

```bash
docker compose exec db psql -U minilp -c \
  "SELECT id, status, variant, leased_by FROM slots WHERE id = <slot_id>;"
# → status 'open', variant unchanged, leased_by NULL
```

That is the difference between leaving and abandoning: the unit is available to
the next annotator immediately rather than after the lease expires.

- Pick an answer *without* submitting, then press `x` — you are warned before the
  answer is discarded. Submit first and the exit never asks.
- Keyboard-only round trip: from home, tab to a project's **Label**, `Enter`, then
  answer with the number keys, `Enter` to submit, `x` to return. No mouse.

**The review queue** (run the judges on project 6 first — step 2d — or it is
empty, which is itself the correct behaviour):

```
http://localhost:5173/?review=1&annotator=1&key=dev-admin-key
```

(also linked from the admin nav as **Review queue**)

- Each item shows the unit, the proposed answer with its consensus and entropy, a
  vote table naming every rater with its weight and variant, and the judges'
  reasoning traces inline. `demo-judge-cat` should carry visibly more weight than
  `demo-judge-dog`.
- `a` approves and moves to the next item. `n` / `p` walk the queue.
- `o` opens the override editor, which renders the template's **real widgets** —
  pick an answer, add a note, `Enter` to save. `Esc` cancels. `a` deliberately
  does *not* approve while the override is open.
- Decide the last escalated unit and watch the depth counter reach 0; the queue
  then shows an empty state that explains what would put something in it.

**The Active learning section** (project 7, or project 6 for an open batch to
rank). Every project section is its own URL, so this links straight to it:

```
http://localhost:5173/#/admin/project/7/active-learning?key=dev-admin-key
```

- The **Iteration eval curve** card shows
  `demo-student` with three rows, gold accuracy climbing v1 → v2 → v3 — the
  same numbers step 3a printed, rendered as a table.
- Switch to project 6 and the same section, click **Rank next batch** — a table of
  open units appears with disagreement/entropy/score columns; a unit with no
  votes yet shows em-dashes and a score of `0.50`, not zeros.
- Click **Register checkpoint…**, fill in a name/provider/model, submit — the
  curve reloads with a new row under that name, no page refresh needed.
- Picking `openai_compatible` as the provider reveals a **Base URL** field (for
  a local server or your own fine-tuned checkpoint); every other provider hides
  it, and there is no field anywhere for an API key.

**The Marketplace page:**

```
http://localhost:5173/#/admin/marketplace?key=dev-admin-key
```

(also linked from the admin nav as **Marketplace**)

- **Shared bundles** lists the three bundles shipped in the repo
  (`summarization-quality`, `calibrated-mock-judge`, `toxicity-triage`) with
  their kind. Click **View** on one — its full JSON loads into the paste box
  below with no network round trip needed to read it. Click **Import** on
  `toxicity-triage.json` — a result line reports what was created: a new
  template, a new judge config, and a new project (with the judge attached and
  ready to run).
- Uncheck **"For a project bundle, also create the project"** and import
  `toxicity-triage.json` again — this time the result has no project, only the
  template and judge config, so re-importing the same starter kit repeatedly
  doesn't pile up duplicate projects while you're only after the template.
- **Import a bundle** takes a paste or a file upload. Paste `{not json` and
  click Import — a JSON-error message appears and nothing is sent; fix it (or
  paste a real bundle) and it imports normally.
- **Export** lists every template and judge config with a **Download bundle**
  button — click one and the browser downloads the exact JSON `GET .../:export`
  returns.
- Open a project's **Export** tab — a second card below the JSONL formats,
  **"Marketplace bundle"**, downloads that project's template + judges + config
  as one file. Paste that file's contents into the Marketplace page's import box
  and re-import it: a new project appears in the dashboard, its own template and
  judges, the original untouched.

### 6. What "green" should look like

| Check | Expectation |
|---|---|
| `pytest` | 557 passed, 0 failed |
| `ruff check .` | All checks passed |
| `npm run test` | 246 passed (19 files) |
| `npm run build` | typecheck clean, bundle written |
| `docker compose up` | `=== MiniLP demo ready ===`, annotatable in under two minutes |
| step 2d | funnel `escalated: 8`, review depth 8 |
| step 2d | proposal `cat` at ≈ 0.77 — weights 1.00 vs 0.30, not a coin flip |
| step 2g | `skipped` equals the number of units you decided by hand |
| step 2h | funnel `finalized: 8`, exactly one `project.completed` delivery |
| step 3a | gold accuracy 0.1667 → 0.3333 → 0.5 across the three seeded checkpoints |
| step 3c | a 4th iteration appears after registering and running one more checkpoint |
| step 4a | the re-imported template previews with `payload_valid: true` |
| step 4c | importing `toxicity-triage.json` creates a template, a judge config, and a project in one call |

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
| M6 | Authoring (visual template builder — drag-and-drop fields, expanded palette; one editor for template create/edit + project edit; add tasks to a live project) + export (JSONL), `docs/extending.md`, seeded demo | ✅ Done |
| M7 | Judge orchestrator (provider abstraction, judge configs, versioned prompts, response cache, budget caps, dry-run, webhooks) | ✅ Done |
| M8 | Ensembles + routing (calibration-weighted merge, declarative pipeline stages, auto-finalize, review queue UI, `final_labels` provenance) + annotator home (card grid, exit-to-home) | ✅ Done |
| M9 | Active-learning loop (informativeness ranking, batch selection, checkpoint re-enrollment, FT-ready exports, iteration eval curve) | ✅ Done |
| M10 | Marketplace (export/import template + judge-config + project bundles, local shared-bundle directory) | ✅ Done |

> The README GIF listed under M6 in PLAN.md is the one deliverable still open — it
> needs a screen recording of the demo. Everything else in that milestone has landed.

**Where things stand:** M0–M10 are done — every milestone in PLAN.md's roadmap has
landed. You can author a template with no code (or by hand in JSON), create a
project, upload units (`.json`/`.tsv`/paste), label from the keyboard with gold
questions, agreement, reputation and counterbalancing running underneath, **enrol
LLM judges that label through the same loop** — priced before they run, capped
while they run, and measured for order bias exactly like humans — **merge every
vote into one decided label**, auto-finalizing the clear cases and routing the
rest to a keyboard-driven human review queue, watch progress, bias and cost in the
admin UI, grow the project with more tasks, export the result as JSONL that
re-imports cleanly and now prefers the human-decided answer over a recomputed one,
**rank the next batch by informativeness**, **re-enroll a fine-tuned checkpoint as
the next judge version in one call**, watch its gold accuracy and
agreement-with-the-decided-answer on an eval curve across iterations, and now
**export a template, judge config, or whole project (template + judges + routing
pipeline) as a shareable JSON bundle** and import it into a fresh instance — no
new tables, since §4 has carried every one a bundle touches since M1.

## Repo layout

```
MiniLP/
├── backend/          # FastAPI app: api/, models/, schemas/, services/
│                     #   services/: templates, assignment, quality, analytics, ingest, auth,
│                     #     slots, export, judges/ (providers/, prompt, cache, budget,
│                     #     orchestrator), merge/ (merge, weights, finalize, pipeline,
│                     #     review, condition), active_learning/ (selection, checkpoints,
│                     #     iterations), webhooks/, marketplace/ (bundle export/import,
│                     #     local shared-bundle directory)
│                     #   alembic/ migrations · tests/ (pytest, run against real Postgres)
├── frontend/         # React + TS (Vite): annotator home, annotation view, review queue,
│                     #   admin/ (dashboard, progress, unit browser, bias, judges + costs,
│                     #   active learning, template gallery, wizard, builder, marketplace)
├── docs/             # RUNBOOK.md — build · test · reset · run, and what to do when it breaks
│                     # DESIGN.md — decision log + postmortems ("why", not "what")
│                     # extending.md — how to add a display/input type, or a routing stage
├── docker-compose.yml
├── Testing.txt       # manual test scripts, per milestone
├── PLAN.md           # full project plan (§1–§14)
└── README.md
```

## License

MIT (to be added).

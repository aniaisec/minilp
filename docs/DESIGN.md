# DESIGN.md — Decision log

Filled in as milestones land.

## M1 — Template engine + full data model

### Schema-first, entire §4 data model in one migration
All §4 tables (incl. `judge_configs`, `final_labels`, `annotators.kind`, `webhooks`,
`projects.pipeline`) ship in the initial Alembic migration even though the human path
(M1–M6) is the only one exercised. Rationale: no migration pain when judges land in
M7; the assignment/quality/merge engines are template- and annotator-kind-agnostic
by design, so the columns they'll read must exist from the start.

### Counterbalancing: pre-generated slots, not per-render randomization
Variant balance (§2.7) is realized by pre-generating exactly K/n `slots` per variant
value at ingest time (`services/slots/generation.py`), with the variant value stored
on the slot. Per-render randomization can't guarantee exact balance at completion and
can't return an abandoned slot "retaining its variant designation" (§2.7). Pre-generated
slots make the invariant (K/n per value at creation *and* completion) a structural
property we can assert, and they let leasing (M2) reopen a failed slot without breaking
balance. Slot order is shuffled so sessions have no predictable variant rhythm.

### Immutability & versioning (§2.5)
Templates are immutable per `(name, version)`. Built-ins can't be edited — cloning
produces a `kind=custom` draft (this is also how you "edit" a builtin). For custom
templates, a *schema-affecting* edit (inputs added/removed/retyped, options changed,
likert scale changed, variants changed) writes a **new row** with `version+1`; a
*presentation-only* edit (layout, render options, hotkeys, labels, display blocks)
mutates in place. The schema-affecting projection lives in
`services/templates/versioning.py` so the rule is one testable function.

### Roles (`users.role`) separate from annotators
`users` carries access-control roles (admin/reviewer/annotator); `annotators` carries
labeling identity + `kind` (human/model). They're distinct because a model judge has
no `user` (it authenticates as a shared `role=annotator` service user, §4/§5) and
because one human user could, in principle, map to labeling identity independently of
their API role. A CHECK enforces `kind=human ⇒ user_id NOT NULL` and
`kind=model ⇒ judge_config_id NOT NULL`.

### "One valid label per annotator per unit" as a partial unique index
Enforced in the DB, not just the app: a partial unique index on
`labels(annotator_id, unit_id) WHERE is_valid`. `unit_id` is denormalized onto
`labels` (it's reachable via `slot`) specifically so the constraint can be expressed
at the *unit* level, not merely per slot — a variant-balanced unit has multiple slots
and an annotator must not label the same unit twice in any variant (§2.7).

### Tests run on real PostgreSQL (never SQLite)
Per the execution notes, `SKIP LOCKED` and partial indexes must be tested on the real
engine. CI provides a `postgres:16` service and `TEST_DATABASE_URL`. For local runs
with no external services, `tests/conftest.py` falls back to an in-process PostgreSQL
via the `pgserver` package, and builds the schema by running the Alembic migrations
(so the migrations themselves are under test). This keeps `pip install -e ".[dev]"`
+ `pytest` runnable anywhere while honoring the "real Postgres" rule.

## M2 — Assignment engine

### Leasing is a single atomic `SELECT … FOR UPDATE SKIP LOCKED`
`next_task` selects the best eligible open slot and locks it in one statement
(`services/assignment/engine.py::_open_slot_query`), so N concurrent workers —
human or judge — never lease the same slot. Eligibility (annotator-unit
exclusion, gold-ness, priority) is expressed in the `WHERE`/`ORDER BY`, so the
lock is taken on exactly the row we hand out. Proven by `test_concurrency.py`
(N annotators, abandonment, exact per-variant balance at completion).

### State-changing writes are row-locked ORM reads, never read-then-write on cached objects
The app uses `expire_on_commit=False`, so a session keeps a stale view of a slot
it leased earlier. `submit_label`/`skip_task` therefore re-read the slot with
`db.get(..., with_for_update=True, populate_existing=True)` and re-check
`status='leased' AND leased_by=me` under the row lock before writing. Without this
a worker whose lease was reclaimed (expired → swept → taken by someone else) could
write a *second* label onto the same slot (two different annotators, same slot —
the per-(annotator,unit) index doesn't catch it). This is the single most
important correctness decision in M2.

### Unit status is computed under a unit-row lock
`_recompute_unit_status` locks the unit row (`SELECT … FOR UPDATE`) before reading
its slots' statuses. Under `READ COMMITTED`, two workers filling a unit's last two
slots can each miss the other's not-yet-committed fill and both write
`in_progress`, leaving a fully-filled unit stuck. Locking the unit serializes the
computation so whichever writer commits second sees the complete picture and marks
it `labeled`.

### Gold injection is a deterministic deficit rule, not a coin flip
`should_serve_gold(served, golds_served, ratio)` serves a gold when delivered golds
fall behind `floor((served+1)·ratio)`. Deterministic (no RNG) so the injected
fraction is exactly `floor(n·ratio)` and unit-testable, while still interleaving
golds throughout a session. Golds inject independently of priority (§6.4): the rule
picks gold-vs-real, then the same priority-ordered query selects within that pool.

### Expiry sweeper reopens with variant retained
`sweep_expired_leases` reclaims leases past `lease_expires_at` with a single
locked bulk read (`SKIP LOCKED`, so concurrent sweepers/workers never contend),
resetting `status→open, leased_by→NULL` but never touching `variant`. Abandoned,
expired, and voided slots all return to the pool keeping their variant designation,
so counterbalancing survives failure (§2.7). Run opportunistically at the head of
`next_task` and safe to run as a background loop.

### Role gating is rank-inclusive, declared per endpoint
`services/auth/roles.py` hashes API keys (SHA-256) and ranks
`admin > reviewer > annotator`. Endpoints accept a minimum role; listing
`{"annotator"}` also admits reviewers/admins, `{"admin"}` admits only admins. The
gate is injected as a FastAPI **parameter dependency** (`_user: User =
Depends(require_admin)`), not the router's `dependencies=[...]` list, because the
pinned FastAPI build only reliably runs signature-parameter dependencies.

## M3 — Annotation UI

### Hotkey assignment is ported to TypeScript, not fetched from the backend
`hotkeys/assign.ts` is a line-for-line port of `services/templates/hotkeys.py`
(digits for the first choice input, a single shared letter pool for the rest,
reserved-key exclusions, arrow normalization, `o` for Other). Duplicating logic is
normally a smell, but the alternative — asking the API for a key map per task — puts
a network round-trip in the annotator's critical path and makes badges a
render-blocking dependency. The invariant that matters is that badges match what
template validation accepted at save time, so the port is pinned by
`assign.test.ts`, which asserts the exact key map for every gallery template. If the
two ever drift, those tests fail rather than annotators silently seeing wrong keys.

### DEVIATION: canonicalization currently runs client-side (§2.6 puts it on the backend)
§2.6 lists "an optional canonicalizer (raw answer → canonical value) on the backend"
as one of the four extension points, and `submit_label` notes canonicalization is
"layered on in M3/M4". As shipped, the **frontend** computes `value` (positional
Left/Right → item A/B under the slot's `panel_order`; `other:` prefix stripping) and
`POST /tasks/{slot}/submit` stores whatever `value` it is handed.

This is a trust-boundary problem, not just a layering one: a buggy or hostile client
can submit a `value` inconsistent with its `raw`, which would silently corrupt bias
analytics (§9) and merge decisions (§7.2). It also means judge workers (M7) would
have to re-implement the same mapping to stay consistent with humans.

Accepted for M3 because the renderer is the thing that knows the variant→panel
mapping and the milestone is UI-scoped. **Action for M4:** move canonicalization
into a backend service (`services/quality/canonical.py`), derive `value` from `raw` +
`slot.variant` server-side, and treat a client-supplied `value` as advisory only
(compare-and-warn, or reject on mismatch). The frontend function should then be
deleted rather than left as a second source of truth.

**RESOLVED in M4.** `services/quality/canonical.py` now recomputes `value` from
`raw` + `slot.variant` on every submission and stores its own answer; the client's
`value` is ignored. The frontend function was *kept* rather than deleted — see
"Client canonicalization kept as a mirror" below.

### DEVIATION: acceptance covered by jsdom component tests, not Playwright
M3's acceptance names Playwright for "each gallery template renders and submits
end-to-end". Shipped instead: `views/Annotate.test.tsx` (Vitest + Testing Library,
jsdom), which drives the same three criteria — every gallery template renders and
submits, tasks complete via `fireEvent.keyDown` only (no mouse events anywhere in the
suite, which is a stronger guarantee than "we didn't click" in a browser), and the
`?` overlay badges the correct key for every interactive element. Rationale: these
run in-process in CI with no browser download or live stack, so they gate every PR
cheaply. The gap this leaves is real — no actual browser engine, no CSS layout
verification, no proof the Vite build wires up. A Playwright smoke test over the
seeded demo is the right addition when the M6 demo lands.

### Presentation-only render options deferred (§2.2)
Implemented: `collapsible`, `max_lines`, `fit`, `line_numbers`, `language` (as a
label), `waveform`, `playback_speed`. Stubbed or deferred: `sync_scroll` (renders as
a `data-sync-scroll` attribute with no scroll coupling), `diff_highlight`, image
`zoom`/`lightbox` (cursor affordance only), and code syntax highlighting. All four
are presentation-only by §2.2 — they cannot affect stored values — so deferring them
does not invalidate collected labels, and they can land in M5 alongside the other UI
work. `sync_scroll`/`diff_highlight` matter most (side-by-side is the flagship) and
should be first.

### Markdown is a minimal escaped subset, not a library
`render/markdown.ts` escapes HTML first, then applies headings/bold/italic/inline
code/links/lists. Chosen over a markdown dependency because unit payloads are
attacker-influenced in the general case (they're uploaded data rendered into an
annotator's browser), and an escape-first subset is trivially auditable. `html_snippet`
blocks, which by definition carry markup, are isolated in a `sandbox=""` iframe so
embedded scripts cannot run. Revisit if templates need tables/footnotes.

### Theme is set on `<html>`, not the view root
The light/dark tokens are declared under `[data-theme="dark"]`, and `body` draws its
background from `--bg`. Setting the attribute on an inner element leaves `body`
outside the themed subtree, so the page background stays light in dark mode. The
attribute is therefore applied to `document.documentElement` via an effect (restoring
the prior value on unmount so tests don't leak state between cases).

### The progress bar is session-scoped until M5
§11 lists a progress bar in the annotation view, but true project completion needs
`GET /projects/{id}/progress` (M5). Until then the bar tracks labels submitted this
session against a `sessionGoal` prop (default 25) — momentum feedback for the
annotator without inventing a project-completion number the frontend cannot know.

### Auto-submit is restricted to single-input choice templates
§2.4's "auto-submits when the template has a single required input" is implemented as:
exactly one input on the template, of type `radio`/`likert`/`choice_buttons`, and the
chosen value is not an in-progress `Other…` entry. Multi-select (`checkbox`) and free
text are excluded because a keystroke there is rarely the annotator's final answer,
and firing early would cost a label. Everything else submits on `Enter`.

### Not built (deferred by the plan itself)
`span_select` (§2.1 marks it a stretch goal that may slip past M6) and `show_if`
conditional inputs (§2.3 marks it v1.1). The widget registry is a
`Partial<Record<InputType, …>>` so an unregistered type renders a visible
"Unsupported input" placeholder rather than crashing the task.

## M4 — Quality subsystem

### Consensus thresholds are compared to two decimal places
§6.4's own example policy is `min_consensus: 0.67`, which people write meaning
"2 of 3 agree". Compared strictly, 2/3 = 0.6667 < 0.67 and that policy is
*unsatisfiable at K=3* — a trap, not a feature. `key_consensus` therefore adds a
`CONSENSUS_EPSILON` of 0.005 before comparing. The alternative (demand people
write 0.6666667) optimizes for arithmetic purity at the cost of every user getting
it wrong once.

### Kappa is only reported over exact categories
Cohen/Fleiss kappa assumes categorical equivalence classes. `within` (±tolerance)
and `jaccard` (≥threshold) agreement are **not transitive** — A can agree with B
and B with C while A and C disagree — so there is no partition to compute marginals
over. Rather than invent a number, kappa buckets on exact values regardless of the
key's match rule, and the tolerance shows up where it *is* well-defined: the
consensus rate, which is computed pairwise against a candidate answer.

For the same reason `key_consensus` doesn't tally votes with a `Counter` for
non-exact rules; it tries each distinct vote as the candidate and takes the best
support. That's the honest reading of "how many raters agree with each other"
under a tolerance.

### Fleiss drops items whose rater count differs from the mode
The formula assumes a constant n per item. Under dynamic overlap growth (§6.4)
units legitimately end up with different label counts, so mixing them would bias
P_e. Dropping the off-mode items is a visible, explainable loss; silently mixing
them is an invisible, unexplainable bias. `n_items` in the response says how many
actually contributed.

### Reputation uses a smoothing prior so a new annotator isn't at 0.0
`annotators.reputation_score` defaults to 0.0, but a raw gold accuracy of "0
passes out of 0 golds" is undefined, not bad. Composite reputation Laplace-smooths
gold accuracy (`+2 successes / +2 trials`), so someone with no history scores ~1.0
and can be admitted to a `min_reputation` project. Correspondingly,
`check_eligibility` recomputes the score **live** when `min_reputation > 0` rather
than reading the cached column — the cache is only written after a label lands, so
gating on it would lock out every annotator before their first submission.

### A gated annotator gets 403, not an empty queue
`GET /tasks/next` returns 204 for "no work" and now 403 for "you're paused / below
threshold", with the reason in the detail. Collapsing both into 204 would mean an
annotator suspended for gold failures spends an afternoon reloading a page that
says "all caught up". The frontend renders two visibly different screens and stops
polling on the 403.

### The submit response is blinded
`POST /tasks/{slot}/submit` returns only `{paused, labels_voided, reputation,
flags}`. It deliberately omits whether the unit was a gold, whether that gold
passed, and the unit's consensus block. Any of the three would let an annotator
identify golds by watching the response (§6.1 requires they be indistinguishable)
or learn their peers' votes. The full `QualityOutcome` exists in-process and is
reachable through the reviewer-gated analytics endpoints.

### POSTMORTEM: two bugs only manual testing caught (found 2026-07-20)

Both were found during the first real end-to-end pass of the M4 demo — the first
time the actual UI hit the actual API — and both were structurally invisible to
the automated suite. Recorded here because each maps to a known gap that now has
a deadline.

**1. `GET /projects/{id}` and `GET /templates/{id}` never existed.** The
annotation view's first two calls on page load, missing since M3. Every project
URL rendered a "Not Found" card. Not caught because the frontend tests mock the
API client and the backend tests only exercise routes that exist — nothing in CI
proves the two halves agree on the contract. This is precisely the risk the M3
deviation entry accepted when Playwright was deferred; the deferral now has a
hard boundary: **the e2e smoke test lands in M5, not M6** — M5's wizard adds more
frontend↔backend contract surface, and a second round of this class of bug is
not acceptable. (Fix: routes added with a named regression test in
`test_api.py`; `ProjectOut` also gained `guidelines_md`, which the guidelines
panel expected and never received.)

**2. The demo seed announced its golds.** `bootstrap_demo.py` wrote "GOLD — the
expected answer is 'cat'" into unit *payloads* — annotator-visible by design.
The API blinding (see "The submit response is blinded" above) was correct and
tested; the seed data defeated it from the other side. Nothing tests seed
content because seeds aren't code paths. Lesson generalized: **payload content
is part of the blinding surface.** Golds must be indistinguishable in what the
annotator *sees*, not just in what the API *returns* — same discipline as model
names and variant values (§3 "blinded"), and it applies to judge prompts in M7,
where a payload leak would contaminate every judge label at scale. The M6 demo
polish should include a "leak review" of all seeded payloads.
Quality needs to void labels and reopen slots; assignment needs the same on skip
and lease expiry. Rather than have `services.quality` import the assignment engine
(or duplicate the logic and drift), `recompute_unit_status` / `reopen_slot` /
`void_labels` live in the slots package and both import them. The §2.7 invariant —
a reopened slot keeps its variant — is then enforced in exactly one place, which is
why a quality pause preserves counterbalancing for free.

### Growth adds a whole variant round at a time
`grow_overlap` opens *n* slots (one per variant value), not one. Adding a single
slot to a `panel_order` template would break the K/n invariant that §2.7 and §12
call non-negotiable, so the growth step is the variant count and
`max_labels_per_unit` is validated for divisibility at project creation.

### Client canonicalization kept as a mirror, not deleted
The M3 deviation entry proposed deleting `frontend/src/render/canonical.ts` once
the backend owned canonicalization. It was kept: the annotation view needs the
canonical value locally anyway (auto-submit decisions, and eventually optimistic
UI), and sending it lets the two implementations be diffed. The trust boundary is
closed by the server *ignoring* the client's value, not by the client not computing
one. If the two drift, the gallery fixtures used by both test suites are where it
shows up.

### `units.quality` is a cache, not a source of truth
The per-key consensus snapshot is denormalized onto the unit so the M5 unit browser
and progress view can render without recomputing every unit's votes.
`GET /projects/{id}/consensus` recomputes on the fly for units that predate M4, so
the cache being absent or stale degrades performance, never correctness.

### POSTMORTEM: a reload stranded the annotator's own task (found 2026-07-23)

Reported from manual use: a freshly created project showed "All caught up" while
the admin showed the units `in_progress`. Cause: assignment is *pull-based* — the
annotation view leases a slot on page load (`pending → in_progress`), and the
annotator-unit exclusion (§2.7) then hides a unit from the annotator who holds it.
So opening/reloading the page without submitting leased the units to that same
annotator and then excluded them from their own un-submitted holds; the slots sat
leased until `lease_minutes` (default 30) expired.

Two things made this invisible to CI:

1. **No test asserted unit status across the lifecycle.** The suite checked
   `filled → labeled` on submit, but nothing asserted the boring baseline: an
   uploaded unit is `pending` with `open` slots, and *only* leasing moves it to
   `in_progress`. A status assertion "after upload" is now
   `test_fresh_units_are_pending_and_only_leasing_moves_them`.

2. **The old tests actively encoded the buggy behavior as intent.** Two
   assignment tests leased several slots for one annotator *without submitting*
   and asserted they got distinct units — i.e. they baked in multi-lease
   pre-fetch, which is exactly what stranded the task on reload. They passed, so
   the behavior looked correct.

Fix: `next_task` now **resumes an annotator's existing active lease** (refreshing
its expiry) before handing out anything new — one open task at a time, so a reload
returns the in-progress task instead of a dead end. The two tests were rewritten to
verify the real invariants (never the same unit twice; two annotators may share a
unit's slots) via submit-between-leases rather than the multi-lease shortcut.
Lesson, generalized: **test the state a user reads, not just the state a happy-path
transition produces** — the funnel the admin sees is a first-class output and now
has coverage.

(Also this session, from the same manual pass: the `allow_other` "Other…" option
had no click handler — only the `o` hotkey activated it — and single-input
templates auto-submitted on select with no way to review. Auto-submit is now an
opt-in toggle, default off; both are covered in `Annotate.test.tsx`.)

## Planned (later milestones)
- Escalated units are flagged (`units.escalated_at`) but there is no review queue
  to work them yet — that queue, and `final_labels`, are M8 (§7.2)
- Judge-vs-human kappa (`?group=cross`) returns empty until M7 enrolls judges
- Reputation as merge weight (§7.1) — the score exists, nothing consumes it yet
- `sync_scroll` / `diff_highlight` / zoom-lightbox / syntax highlighting (M5, §2.2)
- Playwright smoke test over the seeded demo — **pulled forward to M5** after the
  missing-routes postmortem (M4 section above)

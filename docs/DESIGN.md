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

## M6 — Authoring + export (human-MVP release)

### The builder and the JSON editor share one state object, not two
`TemplateBuilder` renders whichever view is selected over a single
`TemplateSchema` owned by the caller. The JSON view re-serializes from that object
on entry and parses back into it on every keystroke; the canvas mutates it
directly. This is why "switching views never loses work" is structurally true
rather than a feature someone has to maintain — there is nothing to synchronize.
The alternative (a text buffer alongside a parsed model, reconciled on switch) has
a failure mode we would have had to invent: unparseable text with pending canvas
edits, and no honest answer for which wins.

### Client-side validation is a live-feedback port, and says so
`frontend/src/views/admin/builder/validate.ts` re-implements the subset of
`services/templates/validation.py` an author trips over while dragging fields —
missing options, bad bounds, hotkey conflicts. Two implementations of one ruleset
is a real cost; the alternative was a round trip per keystroke, which makes the
"every change re-renders instantly" bar (§2.5) unreachable. The mitigation is
explicit precedence: **the server is authoritative**, its errors render verbatim
*above* ours, and save always goes through it. If the two disagree, the author
sees the server's answer, not a silent divergence.

### Dropdowns and rankings get no per-option hotkeys
`select`, `multiselect` and `ranking` exist *because* the option list is long
enough that radio/checkbox would sprawl. Handing 40 options one key each would
exhaust the 1–9 + letters budget in a single field and collide with every other
input on the page (§2.4). They stay keyboard-*reachable* through native element
semantics (and ranking adds Alt+↑/↓), which is the invariant that actually
matters — "completable without a mouse", not "one key per thing".

### Match rules default per input type, not just per project policy
`exact` compares lists as sets, because a checkbox answer is a set. A `ranking`
answer is a sequence where position *is* the judgment, so the same default would
call `[A,B]` and `[B,A]` identical — silently, in gold grading, consensus and
agreement at once. Rather than require every project to declare a policy for every
ranking key, `rule_for` now takes an optional input type and falls back to
`DEFAULT_MATCH_BY_INPUT_TYPE` (`ranking` → the new `ordered` kind). An explicit
project policy still wins. The three call sites (gold, consensus, reputation) load
the template to supply the types; that is one extra `db.get` on paths that already
hold the project.

### Changing K reshapes slots in whole rounds, and refuses to shrink past work
`update_project` grows overlap by planning a *complete* balanced round per unit
(`plan_slot_variants`), never a partial one — a half-round would break K/n at
completion, which §2.7 states as an invariant rather than a goal. Shrinking only
removes `open` slots and raises `ProjectError` when a unit has already been
labeled or leased past the new K. Both alternatives there are worse than failing:
deleting a filled slot destroys a collected label, and leaving it inflates the
unit past its stated overlap. The error names the unit so the admin can act on it.

### A project-level template edit always clones and rebinds
Editing the schema from the project editor never mutates the bound template, even
when the change is presentation-only and even when the template is custom. The
rule is boring on purpose: an admin editing *their project* should not have to
know whether some other project shares the template. Template-level editing
(`PUT /templates/{id}`) keeps the full §2.5 versioning nuance — update in place vs
bump — because there the object being edited is unambiguous.

### The `labels` export is also the re-import format
Export rows put `payload`, `is_gold`, `gold_expected` and `priority` exactly where
`units:bulk` reads them, with the analysis fields (`final_label`, `consensus`,
per-label provenance) alongside as extra top-level keys ingest ignores. So
"export re-imports cleanly" (§12 M6 acceptance) needs no transformation step, and
an export doubles as a backup. `raw` deliberately includes voided labels flagged
`is_valid: false`: a bias study needs to know a rater was removed, not to have
their rows vanish.

Exports materialize before the response starts rather than streaming lazily — a
format mismatch (preference on a classification project) must be a 422 with an
explanation, not a 200 that truncates after two rows.

### The demo is bootstrapped by the container entrypoint
`docker compose up` → annotate in under 2 minutes (§12 M6) is not reachable if the
first step is reading the README to find which script to `exec` into the container.
`backend/entrypoint.sh` migrates, seeds the gallery, and — when
`MINILP_BOOTSTRAP_DEMO=1`, which compose sets — bootstraps the demo and prints
ready-to-open URLs into the log. Both steps are idempotent, so restarts are safe,
and the flag defaults to off in the image so a real install isn't seeded with toys.

### The preview is a column, and the breakpoints are answering two questions
The builder first shipped with the live preview stacked *below* the editor inside
a 1180px-capped admin shell — so on a normal window the thing being built was off
the bottom of the page and effectively invisible while you built it. It is now a
right-hand column that sticks as you scroll, collapsing to the bottom on a narrow
window.

The two breakpoints deliberately use different mechanisms, because they answer
different questions:

- **Shell split** (`.mlp-builder-shell`) — "is the *window* wide enough to show
  the preview beside the editor?" That is genuinely about the viewport, so it is
  a media query at 1280px.
- **Editor columns** (`.mlp-builder`) — "is the *work column* wide enough for
  palette + canvas + inspector?" That depends on whether the preview just took a
  third of the width, so it is a container query on the work column. A media
  query here would be guessing at a width it cannot see, and would be wrong in
  exactly the case that matters (wide window, split shell).

Both are pure CSS: no resize listener, no piece of React state that can disagree
with the window. `.mlp-admin-main` lost its `max-width` at the same time — views
that read better narrow (dashboard, wizard, most project tabs) set their own, and
the two that want the room (builder, gallery) stop being boxed into a column.

### Postmortem: the options editor ate every newline
The inspector's "options, one per line" box rendered `options.join("\n")` while
storing `split("\n").filter(Boolean)` — so pressing Enter produced a trailing
blank line, which was filtered out, which removed the newline, which ran every
option together into one. The same bug hit the comma-separated hotkeys field.
Caught by `TemplateBuilder.test.tsx` typing multi-line text the way a person does,
not by asserting on a pre-built schema.

Fix: `BufferedText` keeps the literal typed text in local state and emits the
parsed value on every keystroke, so live validation and preview still work.
Generalized lesson: **a control whose displayed value is derived from a lossy parse
of its own input will eat characters** — keep the buffer, derive the value.


## M7 — Judge orchestrator

### A judge reaches work through `next_task`, not through a query of its own
The orchestrator's loop is `next_task` → assemble → call → parse → `submit_label`.
It could have selected open slots directly and been simpler to read. It does not,
because every guarantee M2–M4 established lives in those two functions: `SKIP
LOCKED` leasing, the K/n variant balance, gold injection at `gold_ratio`, the
annotator-unit exclusion, lease expiry, server-side canonicalization, gold
grading, reputation, consensus growth. A judge-specific query would have had to
reimplement all of it and would have drifted from it on the first change.

The evidence that this was the right call: `services/judges/` contains no
reference to slots, variants, golds or reputation, and no file outside it grew a
`kind == "model"` branch. "A judge fills slots respecting balance and golds" —
the M7 acceptance criterion — is true without a line of code that makes it true.

### The prompt shows positions, not items
A judge sees the panels **in its slot's variant order**, labeled "Left"/"Right",
and answers with a side. The obvious alternative — serialize as "Response A" /
"Response B" and let the model answer in canonical space — is what most judge
harnesses do, and it silently destroys the headline metric: the judge would
answer in the same space we store, `raw` would equal `value`, and every
order-bias figure in §9 would read exactly 0.5 by construction. Not because the
model is unbiased, but because we never gave it a chance to be biased.

Rendering positionally means the *existing* canonicalizer (`canonicalize_positional`)
maps side → item for judges exactly as it does for humans, and
`/analytics/bias` reports LLM order bias with confidence intervals for free. This
is the same argument as §2.8's raw/canonical split, applied one layer out.

### Prompt assembly is the fifth blinding surface
DESIGN.md's postmortem 2 generalized "payload content is part of the blinding
surface" and flagged that it would matter for judge prompts at scale. It does:
`prompt.py` never emits `is_gold`, `gold_expected`, the variant dimension, the
raw source keys (`response_a`), or a model name. A gold unit serializes
identically to any other unit, because a judge told "this one is scored" is not
measuring the same thing the gold is meant to measure.

### The cache key includes the variant, and the prompt hash is a guard
§4 fixes the key as `(judge_config + prompt_version, unit, variant)`. Dropping
the variant would roughly halve spend on a side-by-side project and would
manufacture perfect order-consistency — a cache that improves your metrics is a
cache that is lying. Separately, the assembled prompt's SHA-256 rides along and a
mismatch is treated as a *miss*: if the text changed while the version did not,
answering from cache would attribute an answer to a prompt nobody sent.

### Budget spend is read back from `labels`, never accumulated in memory
`judge_spend` sums `labels.cost_usd` for the judge's annotator on the project.
An in-process counter would be faster and would reset at exactly the moment it
matters — a crash, a restart, a second concurrent run, a manual re-run. Caps are
checked *before and after* each call for the same reason: checking only before
overshoots by one call, checking only after overshoots by one call and pays for
it.

### An unknown model price is `unpriced`, not `$0.00`
`resolve_price` returns `priced=False` for a model it has no entry for, and the
API and UI both surface that. Falling back to zero would have been one less
field and would have produced budget caps that never trigger, silently. The same
instinct rejects unknown keys in `judge_configs.budget` at save time: a typo'd
`dayly_usd` that quietly disables a cap is precisely the failure caps exist to
prevent.

### `next_task` grew an `exclude_units` argument
Releasing a lease reopens the slot for *everyone, including the releaser* — fine
for a human pressing skip once, an infinite loop for a judge worker that pulls in
a tight loop. Found by `test_an_unparseable_reply_releases_the_slot_and_is_reported`,
which asserted two attempts and got a hundred.

The fix is a caller-supplied, non-persisted exclusion set rather than a new slot
status or a "cooldown" column: the units a caller has already tried *this pass*
is knowledge that belongs to the pass, not to the database. Nothing is written,
so the work stays instantly available to every other worker, and the exclusion
evaporates when the run ends. A persisted flag would have needed a reaper.

### Webhook delivery is fire-and-forget *and* recorded
§7.3 says delivery is fire-and-forget, and `emit` never raises — a judge run that
completed its work must not report failure because a listener's endpoint is down.
But "fire and forget" without a trace makes a webhook that has been quietly
404ing for a week indistinguishable from one that never needed to fire, which is
a discovery you make when the invoice arrives. Every attempt-set writes a
`webhook_deliveries` row with the signed payload, the final status and the
attempt count. It is also what lets "budget cap fires its webhook" be a real
assertion about the event and its signature rather than a mock-patching exercise.

The signature is HMAC over the exact serialized bytes, not over a re-encoding of
the payload dict — a receiver that re-serialized the JSON to verify would compute
a different digest and fail every check.

### The mock provider ships in `app/`, not `tests/`
It is a real provider class implementing the real contract. Three things need a
judge that is deterministic, instant and free: the acceptance suite (which must
assert on *what* was answered), `docker compose up` (requiring an API key to see
the feature at all is a poor first five minutes), and anyone evaluating the
orchestrator before pointing it at a paid endpoint. Determinism comes from
hashing the prompt, so the same unit always draws the same answer and different
units draw different ones — a stable but non-trivial distribution, enough to
exercise agreement, golds and bias with no network.

### API keys are named, never stored
A judge config carries `params.api_key_env` — the *name* of an environment
variable — and the key is read at call time. The config row, and therefore any
exported M10 bundle, is shareable without carrying a credential. The judge form
has no API-key field at all, deliberately; `JudgesPanel.test.tsx` pins that.


### Deleting a template is three refusals and one deletion
`DELETE /templates/{id}` refuses builtins, refuses in-use versions, and refuses a
partial lineage. All three come from one rule: **a template is the definition of
every label collected under it**, so it may only go away when nothing depends on
it existing.

The FK is already `ondelete="RESTRICT"`, so the database would refuse an in-use
delete regardless. The check in the service exists to turn an `IntegrityError`
into a sentence — "in use by 'Q3 preference run' (#4)" rather than a constraint
name. `GET /templates/{id}/usage` exposes the same information *before* the
click, which is why the gallery's Delete button can be disabled with the reason
next to it instead of live-and-then-409.

Builtins are refused for the reason `edit_template` already refuses them, plus
one more: the seeder recreates the gallery on every boot, so a builtin delete
would silently undo itself. A delete that does not stay deleted is worse than one
that says no.

The lineage delete is all-or-nothing because the alternative — delete the free
versions, keep the used ones — leaves a template's history with holes in it and
the caller believing the operation succeeded. It also skips builtins sharing the
name, since the lineage query is name-based and "delete everything called X"
quietly including a builtin X is the kind of thing that only surfaces in
production.

Soft-delete (archive) was the considered alternative. It was rejected because
nothing else in the schema is soft-deleted, and an `archived` flag would have to
be honoured by the gallery, the wizard, the builder, the project editor and the
M10 bundle exporter — five places that can each forget. The refusal keeps the
in-use case correct with no flag at all.

### `/me` bridges users and annotators, and only on POST
`users` and `annotators` are separate by design (§4): one is an access principal,
the other a rater. Nothing needed to bridge them until an admin wanted to *try*
the project they had just configured — they hold a user token and have no idea
what their annotator id is, or whether they have one.

`POST /me:annotator` is get-or-create and returns **200, not 201**, because the
caller asked to *have* a rater record, not to make a second one. Two annotator
rows for one user would split their reputation and would let them label the same
unit twice, which the §2.7 exclusion exists to prevent. `GET /me` deliberately
does not create: a page load must not insert rows.

The admin labels **as themselves**, not in a preview mode. Their labels count,
are attributed in the roster, and are graded against golds like anyone else's —
which is the honest arrangement, and also the only one that does not require a
second, unmeasured code path through submit.

## M8 — Ensembles, routing, and the annotator home

### Routing is the last stage of the quality pipeline, not a service beside it

`on_label_submitted` gained a step 6: once a unit has stopped collecting, run the
project's routing pipeline. Principle 5 says quality is a pipeline rather than a
report, and "labels become *a* label" is the end of that pipeline, not a separate
concern that happens to read the same rows. The practical consequence is that
nothing in the API layer, the judge orchestrator or the admin surface has to
*remember* to route — every path that writes a label goes through `submit_label`,
and every one of them therefore routes.

The import is lazy at that call site. `merge` reads `quality`'s match rules and
entropy (§6.3/§6.4) at module scope, so a top-level import in both directions is a
cycle; the dependency that matters — *quality's rules are merge's rules* — is the
one kept at module scope, and the tail call is the one deferred.

### The shipped default applies to projects that never asked for it

§7.2 says the default pipeline "ships as" ensemble → auto_finalize → human_review.
`effective_pipeline()` therefore returns it whenever `projects.pipeline` is null,
including for projects created under M1–M7. That is a real behaviour change: a
unit whose K labels agree now reaches `finalized` where before it stopped at
`labeled`.

The alternative — routing only projects with an explicit pipeline — was rejected
because it makes "default" mean two different things depending on when a project
was created, and because `slots/lifecycle.py` has said since M2 that "`finalized`
is owned by later milestones (merge/review)". Four existing assertions expected
`labeled`; they were testing *"collection is complete"* and now say so. The
change is recorded here rather than buried in a diff because it is the one place
M8 alters what earlier milestones do.

### Voiding evidence unwinds an automatic decision — but not a human one

`void_labels` now deletes an `auto_consensus` final label and lets
`recompute_unit_status` leave `finalized` (via an explicit `force` flag, so the
"finalized is not ours to overwrite" rule still holds everywhere else). A decision
that survives the disappearance of everything it was made from is not a decision.

A `human_approved` / `human_override` row is left alone. A reviewer's verdict is
not evidence that can be withdrawn by discrediting the raters underneath it — they
looked at the unit. This asymmetry is also what makes `POST /projects/{id}/route`
safe to press twice, and is asserted from both sides.

### Conditions are parsed, not evaluated

A stage's `if` is a string from `projects.pipeline` — i.e. from the network, from
a PATCH, later from an imported marketplace bundle (M10). `services/merge/
condition.py` is a ~120-line recursive-descent parser over a grammar with no
calls, attributes, indexing or assignment: there is nothing to escape *from*,
rather than a denylist of things to escape *with*.

**An unknown identifier raises.** Returning false would make a typo'd rule
silently never fire, which is the worst failure mode routing has — units pile up
in review with nothing to point at. `validate_pipeline` runs the same parse at
save time against the variable *names*, so `consensuss >= 0.9` is a 422 on the
project edit rather than a discovery three thousand units later.

### Consensus is the minimum key; entropy is bucketed by the match rule

A unit is only as decided as its least-decided input — auto-finalizing because two
of three keys were unanimous is how bad labels get into a training set. So
per-unit consensus is `min` over keys and entropy is `max`.

Entropy is computed over **match-rule buckets**, not distinct raw values. This was
found by an existing M4 test: a likert key declared `{"match": "within",
"tolerance": 1}` counts votes of 4 and 5 as agreeing in §6.4, but raw vote entropy
called them maximally divergent, so the default pipeline escalated a unit the
project had explicitly declared to be in agreement. One notion of "the same
answer", used by consensus, merge and entropy alike.

### Merge weight is the reputation, with a floor

No second scoring system: `merge_weight(a) = clamp(a.reputation_score, 0.05, 1.0)`,
because §6.2 already ends by saying a judge's calibration score doubles as its
merge weight. The floor exists so a rater who has genuinely earned 0.0 is
negligible rather than *deleted* — a unit whose only voter is discredited would
otherwise merge to "unanimous" with no votes at all.

Weights are read live and never cached onto labels: a merge recomputed tomorrow
with better calibration data should produce a better answer. The *provenance* of a
finalized label does record the weights used at decision time, so the decision
stays explainable after the weights move.

Below §6.1's pause threshold the story is different and deliberately so: the
annotator is paused and their work voided, so they stop voting entirely.
Down-weighting is for the merely mediocre. Both halves are asserted.

### One `final_labels` row per unit, updated in place

Keeping every decision as a new row sounds like better history until the third
query has to remember the `ORDER BY`, or an export quietly emits two rows for one
unit. The labels are already immutable, and `provenance` records the decision that
produced the row — including, on an override, the proposal the reviewer rejected.
So the table answers exactly one question and answers it with one row.

### `x` was added to the reserved key set, on both sides

§11 notes that `Esc` is the natural key for leaving and is already §2.4's "clear
selection", so the exit key had to be "chosen without colliding". Choosing an
unused-looking letter would have been a collision waiting for a template with
enough options; §2.4's actual mechanism for a global action key is the reserved
set, so `x` joined `s`/`g`/`d`/`u` in **both** `services/templates/spec.py` and
`hotkeys/assign.ts`, and left `LETTER_KEYS`. Auto-assignment can no longer reach
for it and a template requesting it fails validation at save time — the collision
is impossible rather than unlikely.

### The review queue is one screen, on purpose

A queue item carries the payload, the merged proposal, and every vote with its
weight, variant and reasoning trace. A reviewer who has to open a second view to
learn *why* the ensemble proposed something will stop looking, and a review queue
whose decisions are uninformed is worse than none. The override editor renders the
template's real widgets through the same registry the annotation view uses, so
overriding a ranking is a ranking, not a JSON box.

### Home renders both views from one fetch

The M8 acceptance criterion is that the home page's counts "reconcile exactly with
`/tasks/available`". The way to guarantee that is not to test it harder but to
make disagreement unrepresentable: one fetch, two renderings, and toggling the
view does not re-ask the server. `/tasks/available` already applies the assignment
engine's own exclusion, so what home shows is what the annotator will be served.

### Backlog fires on the crossing, and again if the backlog re-forms

Escalations arrive one at a time, so "depth just became the threshold" is exactly
the moment a backlog formed — no flag column, no dedupe table. If a reviewer
drains it and it re-forms, it fires again, which is the useful behaviour: a
backlog that came back is news. `project.completed` is different — a project
completes once — so it checks the `webhook_deliveries` audit trail rather than
introducing a flag, on the grounds that the event only matters if somebody
subscribed, and if somebody subscribed the row exists.

## M9 — Active-learning loop

"You train, MiniLP loops" (§8): training happens in the user's own stack, and
M9 owns exactly three things — which units to label next, re-enrolling a
fine-tuned checkpoint, and the eval curve that says whether it helped.

### The loop adds no schema, and that is the headline claim

Every M9 table already existed. Batch selection reads the consensus rate and
vote entropy §6.4 already computes; re-enrollment is `judges.new_version`
(§2.5's immutable-per-version rule) followed by `judges.attach_judge` (§7.1) —
literally the same two calls a human clicking through the Judges tab makes;
the eval curve reads `quality.reputation.gold_accuracy` and `final_labels`
(§7.2). The M7 provider docstring already said the punchline before M9 was
written: a fine-tuned checkpoint is the `openai_compatible` provider class, a
different `base_url`, no new code. M9 is the sentence made callable, not a new
subsystem next to it.

### An iteration *is* a `prompt_version`, not a second counter

§2.5 already makes a judge config immutable per prompt version, specifically
so a label stays attributable to the exact config that produced it. §8's
example — "register the new checkpoint as `local-ft-v3`" — is that same
version number, read as a loop iteration instead of a prompt edit. Keeping a
parallel `iteration` column would let the two drift (a config edited three
times but re-enrolled twice) and would answer a question nobody asks
independently of "which version". `POST .../checkpoints:register` is sugar
over `new_version`/`create_judge_config` + `attach_judge` for exactly this
reason — one call for the loop's "re-enroll" step, still one counter.

### Informativeness is a weighted mean over whichever signals exist, not three separate rules

`disagreement` (1 − the worst key's consensus rate), `entropy` (mean per-key
vote entropy — `vote_entropy`'s own docstring already named "active learning
(§8)" as a consumer before M9 existed), and `confidence` (1 − the student
judge's own reported confidence, when `judge_config_id` is given) are averaged
over whichever of the three actually have data, the same shape
`reputation.compute_reputation` uses for its own components (§6.2). A brand
new unit with no votes and no judge confidence yet has no signal indicating it
is hard, so it scores at a neutral 0.5 rather than 0.0 or crashing — 0.0 would
rank it as *certainly easy*, which is not a claim anything here can support.
Finalized units are dropped from the pool entirely (a `NOT EXISTS` against
`final_labels`) rather than scored low: there is nothing left to be
informative about once a unit is decided.

### `agreement_vs_final` is not `peer_agreement` with a different name

`quality.reputation.peer_agreement` (§6.2) compares a rater's answer to the
*peer majority* on units with multiple labels — a purely statistical measure
that has no idea whether a human later overrode the ensemble. §8 step 4 asks
for "agreement-vs-final-labels", specifically because a reviewer's override
(§7.2) is the interesting disagreement an eval curve should show, and peer
agreement cannot see it (the majority might still say what the judge said even
after a human overruled it). `agreement_vs_final` reads `final_labels.value`
directly, so a checkpoint's score reflects what was actually decided, override
included.

### The generic-labels export now prefers the decided row

Noted here as a "planned" item before M9 landed: exports recomputed a "final
label" from live consensus rather than reading `final_labels`, which meant an
export taken after a human override still showed the ensemble's rejected
proposal. `export.jsonl._labels_rows` now reads `final_labels` first and falls
back to the same consensus computation only for a unit still collecting votes
— an export is a training-set source (§10), and training on the ensemble's
mistake instead of the human's correction would be a silent regression baked
into every downstream fine-tune. `preference`/`sft` are unchanged: §10 does not
ask for that treatment there, and both already build their pairs from votes
for a reason unrelated to finalization (RLHF pairs need every vote, not the
decided winner).

### The demo pins a gold distribution rather than approximating "learning"

"A toy student model improving over 3 iterations" needs the accuracy numbers
to be exact, not merely trending up on average — flaky-by-luck is a demo
nobody trusts twice. `bootstrap_demo.py`'s AL project gives each of three
fresh batches the same six-gold mix (1 bird, 2 dog, 3 cat) and pins each
checkpoint's mock answer to a different one of those three answers, so gold
accuracy is 1/6, then 2/6, then 3/6 by construction — the same technique
`ENSEMBLE_JUDGES` already uses to make M8's demo disagreement guaranteed
rather than probable. `gold_threshold: 0` turns off the pause-and-void cliff
(§6.1) for the same reason `test_merge.py`'s synthetic-judges test does: that
gate exists to protect real annotators from themselves, and would otherwise
void an intentionally-imperfect early checkpoint's labels out from under its
own eval curve.

## Planned (later milestones)
- README GIF (M6) — needs a screen recording of the seeded demo; the only M6
  deliverable not landed
- `span_select`, `image_region` and `audio_segment` (§2.1) — each is a value shape
  plus a widget under the same contract as the M6 palette, not new plumbing
- No pipeline *editor* UI yet: the policy is readable and writable through
  `GET`/`PUT /projects/{id}/pipeline` and validated at save time, but the wizard
  step §11 sketches is not built. The validation endpoint is the hard part and it
  exists; the editor is a form over it
- Judge runs are synchronous and bounded (default 100 slots). A background
  worker would add queues, status polling and retries for a feature whose
  guardrail is already "stop at the cap"; revisit if runs outgrow a request
- `sync_scroll` / `diff_highlight` / zoom-lightbox / syntax highlighting (M5, §2.2)
- Playwright smoke test over the seeded demo — **pulled forward to M5** after the
  missing-routes postmortem (M4 section above)

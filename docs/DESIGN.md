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

## Planned (later milestones)
- Reputation weighting + `min_reputation` assignment gating (M4)
- Dynamic overlap growth on disagreement (M4, §6.4)

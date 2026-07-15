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

## Planned (later milestones)
- Slot leasing with `SELECT ... FOR UPDATE SKIP LOCKED` (M2)
- Reputation weighting (M4)

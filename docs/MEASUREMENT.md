# Measuring MiniLP by collecting labels through it

The automated suites prove the invariants hold. They do not prove the claims in
the README: that the shipped label is better than the raters behind it, that
reputation tracks real rater quality, that golds catch bad raters before they do
damage, that the keyboard-first loop is fast, and that order bias is measured
rather than hidden. The only way to test those is to use MiniLP for what it is
for, collecting labels, against items whose true answers we already know.

This is the plan for doing that: what we measure, how the study is run, what
had to change in the code to make it measurable, and the targets we commit to
before looking at the data.

> Back to the **[README](../README.md)** · operational commands are in
> **[RUNBOOK.md](RUNBOOK.md)** · the design decisions behind the instrumentation
> are in **[DESIGN.md](DESIGN.md#measurement-instrumentation)**.

## 1. What we measure

Six questions, each tied to a claim the README makes.

| | Question | Claim under test | Primary metric |
|---|---|---|---|
| **H1** | Is the shipped label better than its raters? | Quality controls built in; calibration-weighted merge | Shipped accuracy vs single-rater and majority-vote accuracy; lift over majority |
| **H2** | Does routing send the errors to review? | Auto-finalize the clear cases, escalate the rest | Accuracy by `final_method`; escalation rate |
| **H3** | Does reputation measure rater quality, and do golds stop bad raters? | "Reputation = calibration"; pause-and-void | Spearman(reputation, true accuracy); spammer recall, labels-before-pause, false-pause rate |
| **H4** | Is labeling fast and does the loop hold under load? | Keyboard-first; `SKIP LOCKED` leasing | Time on task; skip/exit/expiry rates; SUS score; API p95 latency; integrity under concurrency |
| **H5** | Is order bias measured, not hidden? | Counterbalancing + bias analytics | Planted position bias detected; human/judge first-position rate with CI; balance flag |
| **H6** | What does a model judge buy? | Judges label through the same loop | Judge accuracy vs truth; human-vs-judge κ; $/correct label; judge order bias |

**Ground truth lives outside the platform.** Golds *are* ground truth, but they
feed reputation, pausing and merge weights, so scoring the pipeline against them
would be circular. Every study item carries an `item_id` in its payload (which no
template displays), and a separate **answer key**, one JSONL line per item such as
`{"item_id": "s-0001", "sentiment": "negative"}`, is joined to the exports after
the fact. Golds are drawn from the same pool and scored separately.

## 2. What changed in the code (phase 0, done)

Everything in §1 is computable from what MiniLP already records, with three gaps.
All three are closed in this change:

1. **A skip, an exit or an expired lease left no trace.** `reopen_slot` put the
   slot back and the evidence went with it, so skip rate, abandonment and
   lease-to-answer time could not be measured. There is now a `task_events`
   table (migration `e5f7a9b1c3d5`). The assignment engine appends a row on
   every transition: `leased`, `resumed`, `skipped`, `exited`, `released`,
   `expired` and `submitted`. `POST /tasks/{slot}/skip` takes
   `reason=skip|exit`, exit-to-home sends `exit`, and the judge orchestrator's
   releases log as `released`. The slot behaves exactly as before; only the log
   differs. They are exported as `GET /projects/{id}/export?format=events`, and
   listed in the admin **Export** tab.
2. **Every study participant needs their own identity.** There is no
   user-management API. `python -m app.measure.provision` mints users, API keys
   and human annotators and prints each participant's link. Keys are shown once
   and stored hashed. A re-run leaves existing keys alone, and `--rotate`
   reissues them.
3. **Nothing turned exports into the numbers above.** `app/measure/` adds:
   - `metrics.py`: pure functions (accuracy vs answer key, majority vote,
     Spearman, pause detection, task-flow reconstruction, latency, SUS),
     fixture-tested in `tests/test_measure_*.py`
   - `simulate.py`: raters of known quality driving a project over the real
     HTTP API (§4.2), which doubles as the load test
   - `report.py`: fetches exports and analytics, joins the answer key, and writes
     `report.json` + `report.md` (plus the raw `inputs.json`, so a report can be
     re-rendered offline with `--from-inputs`)

## 3. Study materials

### Projects

Two scored projects, chosen so the study covers both a plain categorical task
and the variant-bearing comparison task the bias machinery exists for:

| Project | Template | Units | K / max K | Golds | Agreement |
|---|---|---|---|---|---|
| **S — sentiment** | `text-sentiment` cloned with the `confidence` input removed (see below) | 300 + 30 golds | 3 / 5 | `gold_ratio 0.1` | `{"sentiment": {"match": "exact", "min_consensus": 0.67}}` |
| **P — preference** | `side-by-side-preference` | 150 pairs + 15 golds | 4 / 6 (divisible by the 2 panel orders) | `gold_ratio 0.1` | `{"choice": {"match": "exact", "min_consensus": 0.75}}` |
| **U — usability survey** | `docs/measurement/sus-survey.template.json` | the 10 SUS statements in `docs/measurement/sus-units.jsonl` | K = number of participants | none | any (not scored for accuracy) |

- **One scored input per template.** The scored key should be the only thing
  consensus and routing decide on. A second, optional input (the stock
  template's `confidence` Likert) would let unrelated disagreement escalate
  units. Clone the template in the builder and drop it.
- **Routing:** keep the shipped default pipeline (`auto_finalize` at
  `consensus >= 0.9 && entropy <= 0.3`, else `human_review`). It is the thing
  under test. Expect a high escalation rate at K = 3. That is a finding to
  report, not a reason to change the rule mid-study. An optional second arm can
  re-route the same collected labels under a relaxed rule (`PUT
  /projects/{id}/pipeline` then `POST /projects/{id}/route`) after the primary
  numbers are frozen.
- **The survey is collected through MiniLP too.** With one unit per statement
  and K = participants, the annotator-unit exclusion is what guarantees each
  person answers each statement exactly once. `metrics.sus_scores` turns the
  `raw` export into 0–100 SUS scores.

### Items and answer keys

- **S:** a public three-class sentiment dataset with adjudicated labels, or ~330
  short reviews curated in-house where two people agree on the answer. Check the
  licence before loading third-party text.
- **P:** pairs built with a known winner. Take one good response, then write a
  deliberately degraded partner (a factual error, a truncation, or an off-topic
  answer). Include ~15% genuine ties (two paraphrases, truth `Tie`) so `Tie`
  gets exercised. Randomize which item is `response_a`; the platform's panel
  order counterbalances presentation on top of that.
- **Spot-check the key.** Two people independently label 50 random items. Every
  point of answer-key error caps the accuracy we can measure, so report the
  key's own agreement alongside the results.
- Golds use the same `item_id` scheme and appear in the answer key too (the
  simulator needs them to answer golds honestly); the report excludes them from
  scoring.

Unit file line: `{"payload": {"item_id": "s-0001", "text": "…"}}`. Gold line: the
same, plus `"is_gold": true, "gold_expected": {"sentiment": "negative"}`.

### Sample sizes

- **Accuracy (H1/H2):** at ~85% accuracy a ±5 pp 95% interval needs
  1.96² · 0.85 · 0.15 / 0.05² ≈ **196 units**. 300 leaves room for coverage gaps.
- **Order bias (H5):** detecting a 56% first-position rate against 50% at 80%
  power needs (1.96 + 0.84)² · 0.25 / 0.06² ≈ **544 positional labels**.
  150 pairs × K 4 ≈ 600.
- **Human labeling budget:** S ≈ 300 × 3 + golds + growth ≈ 1,100 labels at
  ~5 s. P ≈ 150 × 4 + golds ≈ 650 labels at ~15 s. Eight participants × 20
  minutes per project covers both with margin.
- **Reputation correlation (H3)** needs more raters than a pilot has, and human
  raters' qualities are unknown. That is why H3's primary evidence is the
  simulated run (§4.2), where rater quality is planted.

## 4. Running the study

Commands assume the stack from [VERIFY.md §0](VERIFY.md#0-bring-it-up) with
`MINILP_BOOTSTRAP_DEMO=0` (a clean install, so demo projects do not mix in),
`API=localhost:8000` and an admin key in `KEY`.

### 4.1 Phase 1 — dry run (about 1 hour)

Build S and P with 20 units each and label a handful by hand as the admin
(**Label this →** on the project card). Then:

```bash
curl -s -H "Authorization: Bearer $KEY" "$API/projects/$S/export?format=events" | head
docker compose exec backend python -m app.measure.report --api http://localhost:8000 \
  --key $KEY --project $S --answer-key /study/truth-s.jsonl --key-field item_id \
  --input sentiment --out /study/dry-run
```

Pass criteria: every event kind you triggered appears (skip with `s`, leave with
`x`, reload the page to see `resumed`), and `report.md` renders with every
section populated or explicitly "—".

### 4.2 Phase 2 — simulated campaign (no humans; about a day)

Raters with planted qualities, so the pipeline is scored against a truth it cannot
see. Personas (`app/measure/simulate.py`):

| Persona | Accuracy | Think time | Habits |
|---|---|---|---|
| `expert` | 0.95 | 2.5–7 s | skips 2% |
| `typical` | 0.85 | 3–9 s | skips 3%, exits 1% |
| `noisy` | 0.65 | 2–6 s | skips 5% |
| `spammer` | random | 0.3–0.9 s | — (the persona the pipeline must stop) |
| `biased` | 0.85 | 2.5–7 s | picks the first/left option 60% of the time regardless |

```bash
docker compose exec backend python -m app.measure.provision --prefix sim --count 9 \
  --out /study/sim-raters.json
docker compose exec backend python -m app.measure.simulate --api http://localhost:8000 \
  --project $S --raters /study/sim-raters.json --answer-key /study/truth-s.jsonl \
  --key-field item_id --input sentiment \
  --mix typical:5,expert:1,noisy:1,spammer:1,biased:1 --seed 1 --out /study/sim-s-1
docker compose exec backend python -m app.measure.report --api http://localhost:8000 \
  --key $KEY --project $S --answer-key /study/truth-s.jsonl --key-field item_id \
  --input sentiment --planted /study/sim-s-1/planted.json --out /study/sim-s-1
```

- Run S and P each with **three seeds** on fresh projects (a rater cannot label a
  unit twice, so a re-run needs new units or new raters). Report the spread
  across seeds, not one lucky run.
- **Load and integrity:** provision 50 raters. On a 2,000-unit
  `image-classification` project (K 3, gold ratio 0.1) with `--mix
  typical:45,spammer:5 --time-scale 0`, `simulation.json` reports p50/p95/p99
  for `next`, `submit` and `skip` under 50 concurrent raters. Afterwards, check
  no invariant bent:

  ```sql
  -- no annotator holds two valid labels on one unit (must return 0 rows)
  SELECT annotator_id, unit_id FROM labels WHERE is_valid
  GROUP BY 1, 2 HAVING count(*) > 1;
  -- every filled slot has exactly one valid label (must return 0 rows)
  SELECT s.id FROM slots s LEFT JOIN labels l ON l.slot_id = s.id AND l.is_valid
  WHERE s.status = 'filled' GROUP BY s.id HAVING count(l.id) <> 1;
  ```

  and that `GET /projects/{id}/progress` still reports `variants.balanced: true`
  on a variant-bearing run.

### 4.3 Phase 3 — human pilot (6–10 people, about 1 hour each)

1. **Recruit** people who did not build MiniLP. Provision one rater each:
   `python -m app.measure.provision --prefix pilot --count 8 --out raters.json`.
   Send each person only their own link.
2. **Brief (5 min, scripted):** what the task is and that the guidelines panel
   (`g`) has the rules. Mention that quality checks exist without saying which
   items are golds. Keyboard use is encouraged, not required.
3. **Label (2 × 20 min):** project S then P, or P then S. Alternate the order
   between participants to cancel learning effects. Participants use the
   annotator home and leave with `x`, so the exit/skip log is real.
4. **Survey (5 min):** project U in MiniLP, then three open questions
   (hardest moment, what slowed you down, what you would change) on paper or
   as a free-text project.
5. **Observe:** one note-taker records stumbles and questions against a
   timestamp. Those notes explain the numbers.
6. **Review:** one person (not a participant) works the review queue for S and P
   to completion, so `human_approved` / `human_override` accuracy is measured
   too.
7. **Report:** run `app.measure.report` per project (no `--planted`), then
   `metrics.sus_scores` over U's `raw` export.

### 4.4 Phase 4 — model judge (optional; needs a provider key)

Run judges on a **copy** of S and P, not the human projects: a judge fills slots
and changes K for the humans. The `labels` export re-imports through `units:bulk`
unchanged, so a copy costs two calls. Enrol a judge with a budget cap and price
the run first:

```bash
curl -s -X POST -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" -d '{
  "name": "study-judge", "provider": "anthropic", "model_id": "claude-sonnet-5",
  "params": {"api_key_env": "ANTHROPIC_API_KEY"}, "budget": {"project_usd": 10}
}' $API/judges
# attach to the copy, then {"dry_run": true} on /judges:run, then the live run
```

If the dry run reports the model as `unpriced`, add its price in
`services/judges/pricing.py` before the live run, or the budget cap has nothing
to cap. The report's H6 numbers then come from the copy's report: judge accuracy
vs the answer key, judge first-position rate, and $/correct shipped label.

## 5. Targets, set before we look

Adjust these before phase 3 if you disagree. Do not adjust them after.

| | Metric | Target | Evidence |
|---|---|---|---|
| H1 | Shipped accuracy − single human accuracy | ≥ +5 pp | S, P (human) |
| H1 | Lift over majority | ≥ 0 | S, P (human, sim) |
| H2 | `auto_consensus` accuracy | ≥ 95% | S, P |
| H2 | Escalation rate | reported; flag above 25% | S, P |
| H3 | Spammer recall | 100% on every seed | sim |
| H3 | Labels before pause (spammer) | median ≤ 60 | sim |
| H3 | Good raters paused (`expert`, `typical`) | 0 | sim |
| H3 | Spearman(reputation, true accuracy) | ≥ 0.6 | sim |
| H4 | Median time on task | S ≤ 8 s · P ≤ 20 s | human |
| H4 | Mean SUS | ≥ 68 (the commonly cited average) | U |
| H4 | API p95, `next` / `submit`, 50 concurrent raters | ≤ 250 ms, zero 5xx | load |
| H4 | Integrity under load | both §4.2 queries return 0 rows; balance holds | load |
| H5 | `biased` persona's first-position CI | lower bound > 0.5 | sim (P) |
| H5 | Unbiased personas' first-position CI | contains 0.5 | sim (P) |
| H5 | Human first-position rate | reported with CI | P (human) |
| H6 | Judge accuracy, $/correct label, judge bias | reported | judge copy |

## 6. What the numbers can and cannot say

- **Personas are models of raters.** The simulation tests whether the
  *mechanisms* respond correctly to rater quality. It says nothing about how
  often real people are wrong.
- **Answer-key error caps measured accuracy.** Report the spot-check agreement,
  and treat any accuracy near that ceiling as "at the ceiling".
- **Golds from the same pool.** If golds are systematically easier than regular
  items, gold accuracy overstates true accuracy, and reputation with it. H3's
  gold-vs-truth correlation is the check.
- **Client time on task includes reading.** The first task of a session carries
  the guidelines. Use medians, and compare the client figure with the
  server-side lease→submit time from the event log.
- **A paused rater's reputation is not comparable.** Pausing voids their recent
  labels, voided golds drop out of gold accuracy, and the roster's reputation
  for them drifts back toward the prior (a paused spammer read 0.90 in the smoke
  run). The H3 correlations therefore use active raters only; paused raters are
  scored by detection instead.
- **A skip hands the same task straight back.** Skipping reopens the slot for
  everyone, including the rater who skipped it, and nothing excludes it from
  their next pull (pinned in `test_task_events.py`). The report shows it as
  *skips re-served to the same rater*. Read skip counts with this in mind: one
  hard item can produce several skips. Whether to change it is a product
  decision this study should inform, not assume.
- **Eight people are a pilot.** Human-side numbers carry wide intervals, and the
  report prints them. Treat them as directional.

## 7. Deliverables

- `report.md` / `report.json` / `inputs.json` per project and per simulated seed,
  plus `simulation.json` for each simulated and load run
- SUS scores and the open-question notes
- A short write-up, added to this page, stating each target in §5 as met, missed
  or not measured, with the number behind it

## 8. Found by the smoke run

The whole chain (provision → simulate → report) was run end to end before any
study data existed: 60 synthetic units, 8 simulated raters, `--time-scale 0`,
and a scratch database. It already surfaced three things the plan has to account
for:

- **Concurrent fills of one unit deadlocked (now fixed).** Before the fix, 8
  of 206 submits (3.9%) returned HTTP 500, every one a `DeadlockDetected` in
  `submit_label → recompute_unit_status`. `submit_label` now locks the unit
  before inserting the label; the mechanism and the regression test are in
  [DESIGN.md](DESIGN.md#fixed-concurrent-fills-of-one-unit-deadlocked). The
  §4.2 load test is still the place to confirm the H4 "zero 5xx under load"
  target at 50 raters.
- **Skips come straight back.** 5 of 7 skips were re-served to the same rater
  as their very next task (§6).
- **A paused rater's reputation recovers** after the void (§6).

The tooling also behaved as designed. The planted spammer was paused after 15
labels, with none of its scored labels left valid. The `biased` persona was
listed as grey rather than scored as a false pause. The variant-free task
printed "—" for position bias rather than a made-up 50%. With the smoke's
deliberately twitchy gold settings (3-gold minimum, 5-gold window), 0 of 6 good
raters were paused on one seed and 2 of 6 on another. That is exactly the
variance the three seeds in §4.2 are there to expose.

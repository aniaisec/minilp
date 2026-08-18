# Verifying MiniLP by hand

The automated suites are the contract (`pytest` + `vitest`, both green in CI).
This page is for driving the thing yourself — every step below is something
you can watch happen.

> Operational instructions — build, test, reset the database, start each piece,
> and what to do when one of them misbehaves — are in
> **[RUNBOOK.md](RUNBOOK.md)**. The per-milestone scripts these steps were
> distilled from are in **[Testing.txt](Testing.txt)**. Back to the
> **[README](../README.md)**.

## 0. Bring it up

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

## 1. Run the automated suites

```bash
# Backend (needs a real PostgreSQL — see "Local development" in the README)
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

## 2. Backend by hand — merge, routing, review

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

## 3. Backend by hand — active-learning loop

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

## 4. Backend by hand — marketplace bundles

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

## 5. Frontend by hand

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

## 6. What "green" should look like

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

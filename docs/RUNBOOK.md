# RUNBOOK — build, test, reset, run

Everything you need to get MiniLP running and prove it works, in the order you
need it. Commands are **PowerShell** (Windows); the bash equivalent is given
where the two differ.

Two ways to run it, and they are independent:

| | Use when | DB | Ports |
|---|---|---|---|
| **A. Docker** | you want it working, now | container `db` | 8000 · 5173 · 5432 |
| **B. Local** | you are changing code | your own Postgres | 8000 · 5173 |

Prerequisites: **Docker Desktop** for A; **Python 3.12+**, **Node 20+** and a
reachable **PostgreSQL 16** for B. Tests need a real PostgreSQL either way —
`SKIP LOCKED`, partial indexes and the migrations themselves are under test, so
the suite refuses to lie on SQLite.

---

## 0. One-time setup

```powershell
cd C:\my\agents\Projects\MiniLP

# Backend: install with dev extras (pytest, ruff, httpx)
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
cd ..

# Frontend
cd frontend
npm install
cd ..

# Commit hooks (ruff + ruff-format on backend/, whitespace/YAML everywhere)
pip install pre-commit
pre-commit install
```

<details>
<summary>bash / macOS / Linux</summary>

```bash
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # add ,localdb on Python ≤3.12 for a throwaway Postgres
cd ../frontend && npm install
cd .. && pre-commit install
```
</details>

---

## A. Run everything in Docker

```powershell
cd C:\my\agents\Projects\MiniLP
docker compose up --build
```

Three containers start: `db` (Postgres 16), `backend`, `frontend`. The backend
entrypoint **migrates → seeds the gallery → bootstraps the demo → serves**, so
there is nothing else to run. Wait for:

```
=== MiniLP demo ready ===
```

It prints an admin key (`dev-admin-key`) and a URL for every surface.

| | |
|---|---|
| API | http://localhost:8000 (OpenAPI at `/docs`) |
| Frontend | http://localhost:5173 |
| Postgres | `localhost:5432`, user/password/db `minilp` |

Useful variants:

```powershell
docker compose up --build -d          # background
docker compose logs -f backend        # follow the backend log (the demo URLs)
docker compose ps                     # what is running
docker compose down                   # stop, keep the data volume
docker compose down -v                # stop and DELETE the data volume (full reset)
docker compose build --no-cache backend   # rebuild after changing pyproject.toml
```

To start clean without the demo projects (the gallery is still seeded), set
`MINILP_BOOTSTRAP_DEMO: "0"` in `docker-compose.yml`.

> If `docker compose up` hangs on `npm install` / `pip install` behind a VPN, that
> is an MTU mismatch — set `"mtu": 1280` in Docker Desktop → Settings → Docker
> Engine, rather than overriding the network MTU in the compose file.

---

## B. Run backend and frontend locally

### B1. Start a database

Easiest is the compose DB on its own:

```powershell
docker compose up -d db
```

### B2. Backend

```powershell
cd C:\my\agents\Projects\MiniLP\backend
.\.venv\Scripts\Activate.ps1

$env:MINILP_DATABASE_URL = "postgresql+psycopg://minilp:minilp@localhost:5432/minilp"
$env:MINILP_BOOTSTRAP_DEMO = "1"

alembic upgrade head            # schema
python -m app.seed              # gallery templates (idempotent)
python -m app.bootstrap_demo    # demo projects + admin key (idempotent)

uvicorn app.main:app --reload   # http://localhost:8000
```

<details>
<summary>bash equivalent</summary>

```bash
export MINILP_DATABASE_URL=postgresql+psycopg://minilp:minilp@localhost:5432/minilp
export MINILP_BOOTSTRAP_DEMO=1
alembic upgrade head && python -m app.seed && python -m app.bootstrap_demo
uvicorn app.main:app --reload
```
</details>

Environment variables the backend reads (prefix `MINILP_`, also loadable from a
`backend/.env` file):

| Variable | Default | Meaning |
|---|---|---|
| `MINILP_DATABASE_URL` | `postgresql+psycopg://minilp:minilp@localhost:5432/minilp` | where the app writes |
| `MINILP_BOOTSTRAP_DEMO` | `0` | `1` seeds demo projects on start-up (compose sets it) |
| `MINILP_DEBUG` | `false` | verbose mode |
| `TEST_DATABASE_URL` | — | **tests only**; never the app's database |

### B3. Frontend

In a second terminal:

```powershell
cd C:\my\agents\Projects\MiniLP\frontend
npm run dev                     # http://localhost:5173, proxies /api → :8000
```

Point it at a backend on another host/port:

```powershell
$env:VITE_API_URL = "http://localhost:8000"
npm run dev
```

---

## Build

```powershell
# Frontend production build (typecheck + bundle → frontend/dist)
cd C:\my\agents\Projects\MiniLP\frontend
npm run build
npm run preview                 # serve the built bundle

# Typecheck only
npm run typecheck

# Backend has no build step — it is installed, not compiled
cd ..\backend
pip install -e ".[dev]"

# Container images
cd ..
docker compose build            # both images
docker compose build backend    # just one
```

---

## Run the tests

Backend tests need their **own** database, separate from the app's. Create it
once:

```powershell
docker compose up -d db
docker compose exec db psql -U minilp -c "CREATE DATABASE minilp_test;"
```

Then, every session:

```powershell
cd C:\my\agents\Projects\MiniLP\backend
.\.venv\Scripts\Activate.ps1
$env:TEST_DATABASE_URL = "postgresql+psycopg://minilp:minilp@localhost:5432/minilp_test"

pytest                          # 557 tests
ruff check .                    # lint
ruff format --check .           # formatting (CI runs this too)
```

<details>
<summary>bash equivalent</summary>

```bash
export TEST_DATABASE_URL=postgresql+psycopg://minilp:minilp@localhost:5432/minilp_test
pytest && ruff check . && ruff format --check .
```

On Linux/macOS with Python ≤3.12, `pip install -e ".[dev,localdb]"` spawns a
throwaway Postgres automatically and `TEST_DATABASE_URL` is not needed.
</details>

Frontend:

```powershell
cd C:\my\agents\Projects\MiniLP\frontend
npm run test                    # 246 tests, 19 files
npm run test:watch              # watch mode
```

Narrower runs:

```powershell
# Backend — M8 only
pytest tests/test_merge.py tests/test_merge_condition.py tests/test_review_api.py -v
pytest -k "merge or review"     # by name
pytest -x                       # stop at the first failure

# Backend — M9 only
pytest tests/test_active_learning.py tests/test_active_learning_api.py tests/test_bootstrap_demo.py -v
pytest -k "active_learning or checkpoint or iteration_curve"

# Frontend — M8 only
npm run test -- src/views/Home.test.tsx src/views/Review.test.tsx src/views/ExitToHome.test.tsx
npm run test -- -t "exit"       # by test name

# Frontend — M9 only
npm run test -- src/views/admin/ActiveLearningPanel.test.tsx

# Backend — M10 only
pytest tests/test_marketplace.py tests/test_marketplace_api.py -v
pytest -k "marketplace or bundle"

# Frontend — M10 only
npm run test -- src/views/admin/MarketplacePanel.test.tsx src/views/admin/ExportPanel.test.tsx
```

Everything at once, the way CI does it:

```powershell
cd C:\my\agents\Projects\MiniLP\backend
$env:TEST_DATABASE_URL = "postgresql+psycopg://minilp:minilp@localhost:5432/minilp_test"
ruff check . ; ruff format --check . ; pytest
cd ..\frontend
npm run test ; npm run build
```

> `pytest` **skips** (rather than fails) the DB-backed tests when no database is
> reachable, with a message telling you what to set. A run reporting hundreds of
> skips means `TEST_DATABASE_URL` is unset or the DB is down — not that the suite
> passed.

### What green looks like

| Check | Expectation |
|---|---|
| `pytest` | `557 passed` |
| `ruff check .` | `All checks passed!` |
| `ruff format --check .` | `150 files already formatted` |
| `npm run test` | `Test Files 19 passed · Tests 246 passed` |
| `npm run build` | typecheck clean, `dist/` written |

---

## Reset the database for a clean demo

Pick the level of destruction you actually want.

### Level 1 — re-seed only (keeps everything, adds what is missing)

Both scripts are idempotent: existing demo projects are skipped and the admin
key is refreshed. Use this after pulling changes that add a demo project.

```powershell
# Docker
docker compose exec backend python -m app.seed
docker compose exec backend python -m app.bootstrap_demo

# Local
cd C:\my\agents\Projects\MiniLP\backend
$env:MINILP_DATABASE_URL = "postgresql+psycopg://minilp:minilp@localhost:5432/minilp"
python -m app.seed
python -m app.bootstrap_demo
```

### Level 2 — drop and recreate the app database (full reset, keeps the volume)

```powershell
cd C:\my\agents\Projects\MiniLP
docker compose up -d db

# Stop the backend first — its connection pool holds the database open and the
# DROP will otherwise block forever.
docker compose stop backend
docker compose exec db psql -U minilp -d postgres -c "DROP DATABASE IF EXISTS minilp;"
docker compose exec db psql -U minilp -d postgres -c "CREATE DATABASE minilp;"

# Still blocked? Something else is connected. Evict it and retry the DROP:
docker compose exec db psql -U minilp -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'minilp' AND pid <> pg_backend_pid();"
docker compose start backend        # entrypoint re-migrates, re-seeds, re-bootstraps
docker compose logs -f backend      # wait for '=== MiniLP demo ready ==='
```

Local backend instead of the container:

```powershell
cd C:\my\agents\Projects\MiniLP\backend
$env:MINILP_DATABASE_URL = "postgresql+psycopg://minilp:minilp@localhost:5432/minilp"
alembic upgrade head
python -m app.seed
python -m app.bootstrap_demo
```

### Level 3 — nuke the volume (also resets Postgres itself)

```powershell
cd C:\my\agents\Projects\MiniLP
docker compose down -v          # deletes the pgdata volume
docker compose up --build       # rebuilds and re-bootstraps from empty
```

### Level 4 — empty the tables, keep the schema

Fastest for a repeatable demo, and what the test suite does between runs. No
migrations re-applied.

```powershell
docker compose exec db psql -U minilp -c "TRUNCATE templates, projects, batches, units, slots, labels, final_labels, users, annotators, judge_configs, judge_runs, judge_cache, reputation_events, webhooks, webhook_deliveries RESTART IDENTITY CASCADE;"
docker compose exec backend python -m app.seed
docker compose exec backend python -m app.bootstrap_demo
```

> **Never point a reset at `minilp_test`.** The test database is recreated by the
> suite; resetting it by hand only costs you the next run's setup time.

---

## What the demo gives you

After a bootstrap, the log prints the ids. On a clean database:

| Project | Shows off |
|---|---|
| 1 · Image classification | the annotation loop, K=1 |
| 2 · Text sentiment | multi-input template |
| 3 · Side-by-side preference | counterbalancing + a mock judge (M7) |
| 4 · Content review rubric | every M6 builder field type |
| 5 · Quality (golds + consensus) | gold grading, pause-and-void, overlap growth |
| 6 · **Ensemble + review queue** | **M8** — two judges that always disagree |
| 7 · **Active-learning loop** | **M9** — a toy student model, three checkpoints already run, gold accuracy 1/6 → 2/6 → 3/6 |

Key URLs (`dev-admin-key`, annotator `1`):

```
http://localhost:5173/?annotator=1&key=dev-admin-key                # annotator home
http://localhost:5173/?project=1&annotator=1&key=dev-admin-key      # annotate
http://localhost:5173/?review=1&annotator=1&key=dev-admin-key       # review queue
http://localhost:5173/#/admin?key=dev-admin-key                     # admin
http://localhost:5173/#/admin/templates/new?key=dev-admin-key       # visual builder
http://localhost:8000/docs                                          # OpenAPI
```

The review queue is **empty until the judges run** — that is correct, not broken.
Fill it:

```powershell
$env:KEY = "dev-admin-key"
curl.exe -s -X POST -H "Authorization: Bearer $env:KEY" -H "Content-Type: application/json" `
  -d '{}' http://localhost:8000/projects/6/judges:run
```

Then reload the review queue: 8 units, each with a merged proposal of `cat` at
≈ 0.77 consensus (weights 1.00 vs 0.30) and both judges' reasoning traces.

Project 7's active-learning loop needs nothing filled — its three checkpoints
already ran at bootstrap. See the eval curve straight away, in the **Active
learning** tab (`#/admin/project/7`) or by hand:

```powershell
curl.exe -s -H "Authorization: Bearer $env:KEY" `
  "http://localhost:8000/projects/7/active-learning/iterations?name=demo-student"
```

The full step-by-step walkthrough — every endpoint, with the outputs to expect —
is in [README.md](../README.md#verifying-it-by-hand).

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `pytest` reports hundreds of skips | `TEST_DATABASE_URL` unset or DB down | `docker compose up -d db`, then set it |
| `connection to server ... failed` | Postgres not running | `docker compose up -d db` |
| `database "minilp_test" does not exist` | first run | `docker compose exec db psql -U minilp -c "CREATE DATABASE minilp_test;"` |
| `DROP DATABASE` hangs | backend pool holding it open | `docker compose stop backend` first |
| `missing API key` in the admin UI | key not in the URL | append `?key=dev-admin-key`, or paste it in the header field |
| Frontend loads, every request 401/404 | backend not up, or wrong port | check `http://localhost:8000/health` |
| Review queue empty | judges have not run | `POST /projects/6/judges:run` |
| `npm run dev` can't reach the API | backend on another host | set `$env:VITE_API_URL` before `npm run dev` |
| Port 5432 already in use | a local Postgres is running | stop it, or change the host port in `docker-compose.yml` |
| CI fails on formatting, local `ruff check` passed | they are different commands | run `ruff format .` |

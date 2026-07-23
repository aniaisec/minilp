"""Shared pytest fixtures.

Tests run against **real PostgreSQL** (the plan mandates it — SKIP LOCKED and
partial indexes must be exercised on the real engine, not SQLite):

- CI / any environment that sets ``TEST_DATABASE_URL`` uses that database.
- Otherwise a throwaway PostgreSQL is started in-process via ``pgserver`` so the
  suite is runnable with no external services. It is an opt-in extra
  (``pip install -e ".[dev,localdb]"``; no wheel for Windows or Python 3.14), so
  when it is not installed set ``TEST_DATABASE_URL`` instead.

If no database is configured *and* pgserver is unavailable, or the configured
database can't be reached, the DB-backed tests **skip** with a clear message rather
than erroring — so `pytest` stays green on a machine without a running Postgres.

The schema is built by running the Alembic migrations (``upgrade head``), so the
migrations themselves are under test. Each test function runs in a transaction that
is rolled back for isolation.
"""

import os
import tempfile

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from alembic import command
from alembic.config import Config

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_NO_DB_HINT = (
    "Start PostgreSQL and point TEST_DATABASE_URL at it, e.g.\n"
    "    docker compose up -d db\n"
    "    TEST_DATABASE_URL=postgresql+psycopg://minilp:minilp@localhost:5432/minilp_test\n"
    '(On Linux/macOS with Python <= 3.12, `pip install -e ".[dev,localdb]"` also '
    "enables an automatic in-process PostgreSQL via pgserver when TEST_DATABASE_URL "
    "is unset.)"
)


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        yield url
        return

    # No external DB configured — spin up an ephemeral PostgreSQL via pgserver.
    try:
        import pgserver
    except ImportError:
        pytest.skip(f"No TEST_DATABASE_URL set and pgserver is unavailable.\n{_NO_DB_HINT}")

    datadir = tempfile.mkdtemp(prefix="minilp_pg_")
    server = pgserver.get_server(datadir)
    try:
        server.psql("CREATE DATABASE minilp_test;")
        # pgserver's uri points at the default 'postgres' db; swap in our test db.
        sock = datadir
        yield f"postgresql+psycopg://postgres@/minilp_test?host={sock}"
    finally:
        server.cleanup()


@pytest.fixture(scope="session")
def engine(database_url: str):
    os.environ["MINILP_DATABASE_URL"] = database_url
    eng = create_engine(database_url, future=True)

    # Fail fast with a friendly skip if the database isn't reachable, instead of
    # erroring every DB-backed test with a raw connection error.
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError as e:
        eng.dispose()
        pytest.skip(f"Cannot reach the test database ({database_url}).\n{_NO_DB_HINT}\n\n{e}")

    # Apply migrations to build the schema (migrations are under test).
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")

    yield eng
    eng.dispose()


@pytest.fixture()
def db(engine) -> Session:
    """A transactional session rolled back after each test."""
    connection = engine.connect()
    trans = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        connection.close()


@pytest.fixture()
def clean_db(engine) -> Session:
    """A committing session that TRUNCATEs all tables afterwards.

    Used by tests that need real commits (e.g. exercising the partial unique index
    or concurrency) rather than a rolled-back transaction.
    """
    session = Session(bind=engine, expire_on_commit=False)
    try:
        yield session
    finally:
        session.rollback()
        session.execute(
            text(
                "TRUNCATE templates, projects, batches, units, slots, labels, "
                "final_labels, users, annotators, judge_configs, reputation_events, "
                "webhooks RESTART IDENTITY CASCADE"
            )
        )
        session.commit()
        session.close()

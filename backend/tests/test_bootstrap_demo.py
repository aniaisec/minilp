"""Regression test for the M9 demo (§12: "scripted loop with a toy student
model improving over 3 iterations"), pinning the same postmortem lesson M4's
`test_gold_regression.py` pins: a demo script that only gets eyeballed once
in a screen recording drifts silently. This asserts the shape a person running
`docker compose up` actually sees.
"""

import contextlib
import io

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

import app.db as appdb
from app.bootstrap_demo import AL_JUDGE_NAME, AL_PROJECT_NAME, main
from app.models import Project
from app.services.active_learning import iteration_curve

TRUNCATE = (
    "TRUNCATE templates, projects, batches, units, slots, labels, final_labels, "
    "users, annotators, judge_configs, judge_runs, judge_cache, reputation_events, "
    "webhooks, webhook_deliveries RESTART IDENTITY CASCADE"
)


@pytest.fixture()
def bootstrapped(engine):
    """Run the real bootstrap entrypoint against the test database."""
    original_bind = appdb.SessionLocal.kw.get("bind")
    appdb.SessionLocal.configure(bind=engine)
    db = Session(bind=engine, expire_on_commit=False)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            main()
        yield db
    finally:
        # Must close *before* the TRUNCATE below: an open session here still
        # holds its transaction (even for reads), and TRUNCATE needs an
        # exclusive lock — leaving this open deadlocks teardown forever.
        db.close()
        appdb.SessionLocal.configure(bind=original_bind)
        cleanup = Session(bind=engine)
        cleanup.execute(text(TRUNCATE))
        cleanup.commit()
        cleanup.close()


def test_the_al_loop_demo_ships_three_checkpoints_with_climbing_gold_accuracy(bootstrapped):
    db = bootstrapped
    project = db.scalar(select(Project).where(Project.name == AL_PROJECT_NAME))
    assert project is not None

    curve = iteration_curve(db, project.id, AL_JUDGE_NAME)
    rates = [p["gold_accuracy"]["rate"] for p in curve["iterations"]]
    assert len(rates) == 3
    assert rates[0] < rates[1] < rates[2]
    assert rates == [
        pytest.approx(1 / 6, abs=1e-3),
        pytest.approx(2 / 6, abs=1e-3),
        pytest.approx(0.5),
    ]
    assert all(p["enrolled"] for p in curve["iterations"])


def test_the_al_loop_demo_is_idempotent_on_a_second_run(bootstrapped):
    """Re-running the entrypoint (a container restart) must not re-label or
    re-register anything — the same lesson M6's demo bootstrap already learned."""
    db = bootstrapped
    with contextlib.redirect_stdout(io.StringIO()):
        main()

    projects = db.scalars(select(Project).where(Project.name == AL_PROJECT_NAME)).all()
    assert len(projects) == 1
    curve = iteration_curve(db, projects[0].id, AL_JUDGE_NAME)
    assert len(curve["iterations"]) == 3

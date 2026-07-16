"""Concurrency acceptance (M2, §12): N simulated annotators hammering the
assignment engine must never double-assign a slot and must preserve exact
per-variant balance — even when leases are abandoned mid-flight.

This exercises the real ``SELECT … FOR UPDATE SKIP LOCKED`` path, so it needs
PostgreSQL (the suite's default). Each thread uses its own Session.
"""

import threading
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Annotator, Label, Slot, Template, Unit, User
from app.services.assignment import next_task, submit_label, sweep_expired_leases
from app.services.ingest.bulk import ingest_units, parse_jsonl
from app.services.projects import create_project
from app.services.templates.seed import seed_templates

NUM_ANNOTATORS = 5
NUM_UNITS = 15
K = 4  # side-by-side: 2 variants → exactly 2 slots per value per unit
ABANDON_PROB = 0.15


def _seed(db) -> tuple[int, list[int]]:
    seed_templates(db)
    tmpl = db.scalar(select(Template).where(Template.name == "side-by-side-preference"))
    proj = create_project(db, name="conc", template_id=tmpl.id, labels_per_unit=K, lease_minutes=30)
    lines = [
        f'{{"payload": {{"prompt": "p{i}", "response_a": "a", "response_b": "b"}}}}'
        for i in range(NUM_UNITS)
    ]
    ingest_units(db, proj, parse_jsonl("\n".join(lines)))
    anns = []
    for i in range(NUM_ANNOTATORS):
        u = User(email=f"ann{i}@x.com", role="annotator")
        db.add(u)
        db.flush()
        a = Annotator(kind="human", user_id=u.id, display_name=f"ann{i}")
        db.add(a)
        db.flush()
        anns.append(a.id)
    db.commit()
    return proj.id, anns


def _total_filled(engine) -> int:
    with Session(bind=engine) as s:
        return s.scalar(select(func.count()).select_from(Slot).where(Slot.status == "filled"))


def test_concurrent_assignment_no_double_and_balanced(clean_db, engine) -> None:
    project_id, ann_ids = _seed(clean_db)
    total_slots = NUM_UNITS * K
    stop = threading.Event()

    def worker(ann_id: int, seed: int) -> None:
        import random

        rng = random.Random(seed)
        session = Session(bind=engine)
        try:
            while not stop.is_set():
                try:
                    slot = next_task(session, ann_id, project_id)
                    session.commit()
                except Exception:
                    session.rollback()
                    continue
                if slot is None:
                    time.sleep(0.005)
                    continue
                if rng.random() < ABANDON_PROB:
                    # Simulate a crashed worker: expire the lease and walk away;
                    # the sweeper must return the slot to the pool, variant intact.
                    slot.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
                    session.commit()
                else:
                    try:
                        submit_label(session, slot.id, ann_id, raw={"choice": "Left"})
                        session.commit()
                    except Exception:
                        session.rollback()
        finally:
            session.close()

    def sweeper() -> None:
        session = Session(bind=engine)
        try:
            while not stop.is_set():
                try:
                    sweep_expired_leases(session)
                    session.commit()
                except Exception:
                    session.rollback()
                time.sleep(0.01)
        finally:
            session.close()

    threads = [
        threading.Thread(target=worker, args=(ann_id, i), daemon=True)
        for i, ann_id in enumerate(ann_ids)
    ]
    sweep_thread = threading.Thread(target=sweeper, daemon=True)
    for t in threads:
        t.start()
    sweep_thread.start()

    # Let the concurrent phase run, then stop.
    deadline = time.time() + 20
    while time.time() < deadline and _total_filled(engine) < total_slots:
        time.sleep(0.05)
    stop.set()
    for t in threads:
        t.join(timeout=5)
    sweep_thread.join(timeout=5)

    # Deterministic single-threaded drain to guarantee completion regardless of
    # thread scheduling. Any leases still held by stopped workers are force-expired
    # (sweep with a far-future clock) so every slot returns to the pool. Correctness
    # (no double-assignment) still holds throughout.
    force_now = datetime.now(UTC) + timedelta(days=1)
    with Session(bind=engine) as s:
        for _ in range(total_slots * 8):
            sweep_expired_leases(s, now=force_now)
            s.commit()
            filled = s.scalar(select(func.count()).select_from(Slot).where(Slot.status == "filled"))
            if filled == total_slots:
                break
            progressed = False
            for ann_id in ann_ids:
                slot = next_task(s, ann_id, project_id)
                if slot is not None:
                    submit_label(s, slot.id, ann_id, raw={"choice": "Left"})
                    s.commit()
                    progressed = True
            if not progressed:
                break

    # --- assertions on the final state ---
    with Session(bind=engine) as s:
        slots = s.scalars(select(Slot)).all()
        labels = s.scalars(select(Label).where(Label.is_valid.is_(True))).all()

        # 1. Every slot filled; exactly one valid label per slot (no double-assignment).
        assert all(sl.status == "filled" for sl in slots)
        assert len(labels) == total_slots
        per_slot = {}
        for lb in labels:
            per_slot[lb.slot_id] = per_slot.get(lb.slot_id, 0) + 1
        assert all(c == 1 for c in per_slot.values())

        # 2. No annotator labeled the same unit twice.
        seen = set()
        for lb in labels:
            key = (lb.annotator_id, lb.unit_id)
            assert key not in seen
            seen.add(key)

        # 3. Exact per-variant balance at completion (K/n per value, every unit).
        units = s.scalars(select(Unit).where(Unit.project_id == project_id)).all()
        for unit in units:
            uslots = s.scalars(select(Slot).where(Slot.unit_id == unit.id)).all()
            counts: dict[str, int] = {}
            for sl in uslots:
                val = sl.variant["panel_order"]
                counts[val] = counts.get(val, 0) + 1
            assert counts == {"AB": K // 2, "BA": K // 2}
            assert unit.status == "labeled"

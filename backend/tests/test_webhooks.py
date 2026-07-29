"""Webhook dispatch, signing, retries and the gold-accuracy trigger (M7, §7.3).

§7.3's promise is that webhooks add no new trigger logic — they fire off checks
that already exist. So the interesting test here is not "does emit() POST", it is
``test_gold_accuracy_drop_fires_its_webhook``: the M4 pause path, unchanged,
producing an M7 event.
"""

import hashlib
import hmac
import json

import pytest
from sqlalchemy import select

from app.models import Annotator, Label, Template, Unit, User, Webhook, WebhookDelivery
from app.services.assignment import AssignmentError, next_task, submit_label
from app.services.ingest.bulk import ingest_units, parse_jsonl
from app.services.projects import create_project
from app.services.templates.seed import seed_templates
from app.services.webhooks import SendResult, emit, sign, subscribers

# --- helpers ----------------------------------------------------------------


class _Recorder:
    def __init__(self, fail_times: int = 0):
        self.fail_times = fail_times
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, url, body, headers):
        self.calls.append((url, body, headers))
        if len(self.calls) <= self.fail_times:
            return SendResult(False, status_code=503, error="upstream down")
        return SendResult(True, status_code=200)


def _hook(db, event="budget.cap_reached", *, project_id=None, secret=None, url="https://a.test/h"):
    hook = Webhook(
        event=event, target_url=url, secret=secret, project_id=project_id, status="active"
    )
    db.add(hook)
    db.flush()
    return hook


def _project(db, name, **kwargs):
    seed_templates(db)
    tmpl = db.scalar(select(Template).where(Template.name == "image-classification"))
    return create_project(db, name=name, template_id=tmpl.id, **kwargs)


def _annotator(db, email):
    user = User(email=email, role="annotator")
    db.add(user)
    db.flush()
    ann = Annotator(kind="human", user_id=user.id, display_name=email)
    db.add(ann)
    db.flush()
    return ann


# --- signing -----------------------------------------------------------------


def test_signature_is_hmac_sha256_over_the_exact_body_sent():
    body = '{"event":"x"}'
    expected = hmac.new(b"key", body.encode(), hashlib.sha256).hexdigest()
    assert sign("key", body) == f"sha256={expected}"


def test_no_secret_means_no_signature_header(db):
    _hook(db, secret=None)
    recorder = _Recorder()
    emit(db, "budget.cap_reached", payload={"a": 1}, sender=recorder)
    _, _, headers = recorder.calls[0]
    assert "X-MiniLP-Signature" not in headers
    assert headers["X-MiniLP-Event"] == "budget.cap_reached"


def test_a_receiver_can_verify_the_signature_over_the_raw_bytes(db):
    """Signing the serialized body (not a re-encoding of the payload) is the
    difference between a verifiable webhook and one that always fails the check."""
    _hook(db, secret="topsecret")
    recorder = _Recorder()
    emit(db, "budget.cap_reached", project_id=None, payload={"z": 1, "a": 2}, sender=recorder)

    _, body, headers = recorder.calls[0]
    expected = hmac.new(b"topsecret", body.encode(), hashlib.sha256).hexdigest()
    assert headers["X-MiniLP-Signature"] == f"sha256={expected}"
    assert json.loads(body)["a"] == 2


# --- subscriber selection ----------------------------------------------------


def test_instance_wide_hooks_receive_every_project(db):
    project = _project(db, "wide")
    _hook(db, project_id=None)
    assert len(subscribers(db, "budget.cap_reached", project.id)) == 1


def test_project_hooks_do_not_receive_other_projects(db):
    a = _project(db, "a")
    b = _project(db, "b")
    _hook(db, project_id=a.id)
    assert len(subscribers(db, "budget.cap_reached", a.id)) == 1
    assert subscribers(db, "budget.cap_reached", b.id) == []


def test_inactive_hooks_are_skipped(db):
    hook = _hook(db)
    hook.status = "disabled"
    db.flush()
    assert subscribers(db, "budget.cap_reached", None) == []


def test_emitting_with_no_subscribers_is_a_no_op(db):
    assert emit(db, "project.completed", payload={}) == []


def test_an_unknown_event_name_is_rejected(db):
    with pytest.raises(ValueError, match="unknown webhook event"):
        emit(db, "budget.exploded", payload={})


# --- delivery records + retries ----------------------------------------------


def test_a_successful_delivery_is_recorded(db):
    hook = _hook(db, secret="s")
    emit(db, "budget.cap_reached", project_id=None, payload={"x": 1}, sender=_Recorder())

    delivery = db.scalar(select(WebhookDelivery))
    assert delivery.webhook_id == hook.id
    assert delivery.status == "delivered"
    assert delivery.attempts == 1
    assert delivery.status_code == 200
    assert delivery.payload["x"] == 1
    assert delivery.signature.startswith("sha256=")


def test_delivery_retries_with_backoff_then_succeeds(db):
    _hook(db)
    recorder = _Recorder(fail_times=2)
    slept: list[float] = []
    emit(db, "budget.cap_reached", payload={}, sender=recorder, sleep=slept.append)

    assert len(recorder.calls) == 3
    assert slept == [0.5, 1.0]
    assert db.scalar(select(WebhookDelivery)).status == "delivered"


def test_a_permanently_failing_endpoint_is_recorded_as_failed_not_raised(db):
    """A judge run that did its work must not be reported as broken because a
    listener is down — but the failure has to be findable afterwards."""
    _hook(db)
    emit(
        db,
        "budget.cap_reached",
        payload={},
        sender=_Recorder(fail_times=99),
        sleep=lambda _: None,
    )
    delivery = db.scalar(select(WebhookDelivery))
    assert delivery.status == "failed"
    assert delivery.attempts == 3
    assert "upstream down" in delivery.error


def test_a_sender_that_raises_does_not_break_the_caller(db):
    _hook(db)

    def exploding(url, body, headers):
        raise RuntimeError("DNS on fire")

    emit(db, "budget.cap_reached", payload={}, sender=exploding, sleep=lambda _: None)
    delivery = db.scalar(select(WebhookDelivery))
    assert delivery.status == "failed"
    assert "DNS on fire" in delivery.error


def test_every_subscriber_gets_its_own_delivery_row(db):
    project = _project(db, "fanout")
    _hook(db, project_id=project.id, url="https://one.test/h")
    _hook(db, project_id=None, url="https://two.test/h")

    recorder = _Recorder()
    emit(db, "budget.cap_reached", project_id=project.id, payload={}, sender=recorder)

    assert len(recorder.calls) == 2
    assert db.scalars(select(WebhookDelivery)).all().__len__() == 2


# --- the trigger that already existed (§7.3) --------------------------------


def test_gold_accuracy_drop_fires_its_webhook(db):
    """M4's pause path, untouched, now produces an M7 event.

    The project's thresholds are lowered rather than 20 golds being planted —
    the same trick the M4 suite uses, and the reason those knobs are config.
    """
    project = _project(
        db,
        "drop",
        labels_per_unit=1,
        gold_ratio=1.0,
        config={"quality": {"gold_threshold": 0.9, "gold_min_samples": 2, "gold_window": 5}},
    )
    rows = [
        json.dumps(
            {
                "payload": {"image_url": f"http://x/{i}.png"},
                "is_gold": True,
                "gold_expected": {"category": "cat"},
            }
        )
        for i in range(3)
    ]
    ingest_units(db, project, parse_jsonl("\n".join(rows)))
    _hook(db, event="gold.accuracy_dropped", project_id=project.id, secret="k")

    annotator = _annotator(db, "sloppy@x.io")
    for _ in range(3):
        try:
            slot = next_task(db, annotator.id, project.id)
        except AssignmentError:
            break  # the pause landed; they are refused further work (§6.1)
        if slot is None:
            break
        submit_label(db, slot.id, annotator.id, raw={"category": "dog"})

    delivery = db.scalar(
        select(WebhookDelivery).where(WebhookDelivery.event == "gold.accuracy_dropped")
    )
    assert delivery is not None, "a paused annotator must raise an alert"
    assert delivery.project_id == project.id
    assert delivery.payload["annotator_id"] == annotator.id
    assert delivery.payload["metric"]["gold_accuracy"] == 0.0
    assert delivery.payload["metric"]["threshold"] == 0.9

    assert db.get(Annotator, annotator.id).status == "paused"
    assert (
        db.scalar(select(Label).where(Label.annotator_id == annotator.id, Label.is_valid.is_(True)))
        is None
    )


def test_no_gold_hook_registered_still_pauses_the_annotator(db):
    """Delivery is a side channel: quality enforcement must not depend on it."""
    project = _project(
        db,
        "nodrop",
        labels_per_unit=1,
        gold_ratio=1.0,
        config={"quality": {"gold_threshold": 0.9, "gold_min_samples": 1, "gold_window": 5}},
    )
    ingest_units(
        db,
        project,
        parse_jsonl(
            json.dumps(
                {
                    "payload": {"image_url": "http://x/0.png"},
                    "is_gold": True,
                    "gold_expected": {"category": "cat"},
                }
            )
        ),
    )
    annotator = _annotator(db, "solo@x.io")
    slot = next_task(db, annotator.id, project.id)
    submit_label(db, slot.id, annotator.id, raw={"category": "dog"})

    assert db.get(Annotator, annotator.id).status == "paused"
    assert db.scalar(select(WebhookDelivery)) is None


def test_units_and_labels_survive_a_pause_for_audit(db):
    """Voided is not deleted — the label stays, flagged."""
    project = _project(
        db,
        "audit",
        labels_per_unit=1,
        gold_ratio=1.0,
        config={"quality": {"gold_threshold": 0.9, "gold_min_samples": 1}},
    )
    ingest_units(
        db,
        project,
        parse_jsonl(
            json.dumps(
                {
                    "payload": {"image_url": "http://x/0.png"},
                    "is_gold": True,
                    "gold_expected": {"category": "cat"},
                }
            )
        ),
    )
    annotator = _annotator(db, "audit@x.io")
    slot = next_task(db, annotator.id, project.id)
    submit_label(db, slot.id, annotator.id, raw={"category": "dog"})

    label = db.scalar(select(Label))
    assert label is not None and label.is_valid is False
    assert db.scalar(select(Unit).where(Unit.project_id == project.id)) is not None

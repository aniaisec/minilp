"""Study-rater provisioning (docs/MEASUREMENT.md).

Keys are shown once and stored hashed; a re-run must not silently invalidate
keys already handed to participants, and ``rotate`` is the only way it does.
"""

import pytest
from sqlalchemy import func, select

from app.measure.provision import provision_raters
from app.models import Annotator, User
from app.services.auth.roles import hash_api_key


def test_creates_a_user_key_and_human_annotator_per_rater(db) -> None:
    raters = provision_raters(db, prefix="pilot", count=3)
    assert [r["name"] for r in raters] == ["pilot-01", "pilot-02", "pilot-03"]
    for r in raters:
        user = db.get(User, r["user_id"])
        assert user.role == "annotator"
        assert user.api_key_hash == hash_api_key(r["api_key"])
        ann = db.get(Annotator, r["annotator_id"])
        assert (ann.kind, ann.user_id, ann.status) == ("human", user.id, "active")
    assert len({r["api_key"] for r in raters}) == 3


def test_a_rerun_leaves_existing_keys_alone_unless_rotated(db) -> None:
    first = provision_raters(db, prefix="p", count=2)
    again = provision_raters(db, prefix="p", count=3)
    assert [r["existing"] for r in again] == [True, True, False]
    assert again[0]["api_key"] is None
    assert again[0]["annotator_id"] == first[0]["annotator_id"]
    assert db.get(User, first[0]["user_id"]).api_key_hash == hash_api_key(first[0]["api_key"])

    rotated = provision_raters(db, prefix="p", count=1, rotate=True)
    assert rotated[0]["api_key"] not in (None, first[0]["api_key"])
    assert db.get(User, first[0]["user_id"]).api_key_hash == hash_api_key(rotated[0]["api_key"])
    assert db.scalar(select(func.count()).select_from(Annotator)) == 3


def test_bad_arguments_are_refused(db) -> None:
    with pytest.raises(ValueError, match="role"):
        provision_raters(db, prefix="p", count=1, role="overlord")
    with pytest.raises(ValueError, match="count"):
        provision_raters(db, prefix="p", count=0)

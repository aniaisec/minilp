"""Who am I, and which annotator am I? (§5 auth, §11.)

`users` and `annotators` are deliberately separate (§4): a user is an access
principal, an annotator is a rater. Most of the time nothing needs to bridge
them — the annotation view is opened with an `annotator=` in the URL, and the
admin surface never labels.

The bridge is needed the moment an admin wants to *try* a project they just
configured. They hold a user token and have no idea what their annotator id is —
they may not have one. `POST /me:annotator` answers "give me the rater record for
whoever this token is", creating it on first use, which is what turns "Start
labeling" in the admin UI into a link rather than a support question.

Creating on POST rather than on GET is not pedantry: a plain read of `/me` must
not quietly insert rows every time a page loads.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_annotator
from app.db import get_db
from app.models import Annotator, User
from app.schemas.api import AnnotatorOut

router = APIRouter(tags=["me"])


def _my_annotator(db: Session, user: User) -> Annotator | None:
    """The human annotator record linked to this user, if one exists."""
    return db.scalar(
        select(Annotator).where(Annotator.user_id == user.id, Annotator.kind == "human")
    )


@router.get("/me")
def get_me(
    user: User = Depends(require_annotator),
    db: Session = Depends(get_db),
) -> dict:
    """The authenticated user and their annotator id (null if they have none).

    Every role can call it — an annotator needs it as much as an admin does, and
    it reveals nothing the caller's own token did not already carry.
    """
    annotator = _my_annotator(db, user)
    return {
        "user_id": user.id,
        "email": user.email,
        "role": user.role,
        "annotator_id": annotator.id if annotator else None,
        "display_name": annotator.display_name if annotator else None,
        "status": annotator.status if annotator else None,
        "reputation_score": annotator.reputation_score if annotator else None,
    }


@router.post("/me:annotator", response_model=AnnotatorOut, status_code=200)
def post_my_annotator(
    user: User = Depends(require_annotator),
    db: Session = Depends(get_db),
) -> Annotator:
    """Get — or create on first use — the annotator record for this token.

    Idempotent, and returns 200 rather than 201 for exactly that reason: the
    caller asked to *have* an annotator, not to make a second one. A user with
    two rater records would split their own reputation and could label the same
    unit twice, which the §2.7 exclusion is specifically there to prevent.
    """
    annotator = _my_annotator(db, user)
    if annotator is None:
        annotator = Annotator(
            kind="human",
            user_id=user.id,
            email=user.email,
            display_name=user.email.split("@")[0] if user.email else f"user {user.id}",
            status="active",
        )
        db.add(annotator)
        db.flush()
    return annotator

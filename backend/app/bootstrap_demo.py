"""Bootstrap a ready-to-use demo: admin user + API key, a human annotator, and a
few projects with units — so the M3 annotation UI can be opened immediately.

Until the admin wizard lands (M5), this is how you create the first user,
annotator, and projects (there is no user/annotator API endpoint yet, §5). It is
idempotent: re-running updates the admin key and skips existing demo projects.

Usage (inside the backend container, after the DB is migrated)::

    docker compose exec backend python -m app.bootstrap_demo

Then open the printed URLs at http://localhost:5173.
"""

import json

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Annotator, Project, Template, User
from app.services.auth.roles import hash_api_key
from app.services.ingest.bulk import ingest_units, parse_jsonl
from app.services.projects import create_project
from app.services.templates.seed import seed_templates

ADMIN_EMAIL = "admin@local"
ADMIN_API_KEY = "dev-admin-key"  # noqa: S105 — local demo key, not a secret
ANNOTATOR_EMAIL = "annotator@local"


def _jsonl(rows: list[dict]) -> str:
    return "\n".join(json.dumps({"payload": p}) for p in rows)


IMAGE_UNITS = _jsonl(
    [
        {"image_url": f"https://picsum.photos/seed/minilp{i}/500/400", "context": "a sample photo"}
        for i in range(1, 7)
    ]
)

SENTIMENT_UNITS = _jsonl(
    [
        {"text": "Absolutely loved this — best purchase I've made all year."},
        {"text": "It arrived on time. Works as described. Nothing special."},
        {"text": "Broke after two days and support never replied. Avoid."},
        {"text": "The plot dragged in the middle but the ending redeemed it."},
    ]
)

SIDE_BY_SIDE_UNITS = _jsonl(
    [
        {
            "prompt": "Explain what a hash map is in one sentence.",
            "response_a": "A hash map stores key-value pairs and uses a hash of the key "
            "to find its slot, giving average O(1) lookups.",
            "response_b": "A hash map is a kind of list you loop through to find things.",
        },
        {
            "prompt": "Give a tip for writing clear commit messages.",
            "response_a": "Write whatever, it doesn't matter.",
            "response_b": "Use an imperative summary under ~50 chars, then a body "
            "explaining *why* the change was made.",
        },
        {
            "prompt": "What's a good way to stay hydrated on a hike?",
            "response_a": "Carry enough water, sip regularly rather than gulping, and add "
            "electrolytes on long or hot hikes.",
            "response_b": "Just drink when you get back.",
        },
    ]
)


def _get_or_create_admin(db) -> User:
    user = db.scalar(select(User).where(User.email == ADMIN_EMAIL))
    if user is None:
        user = User(email=ADMIN_EMAIL, role="admin", api_key_hash=hash_api_key(ADMIN_API_KEY))
        db.add(user)
        db.flush()
    else:
        user.role = "admin"
        user.api_key_hash = hash_api_key(ADMIN_API_KEY)
    return user


def _get_or_create_annotator(db, user: User) -> Annotator:
    ann = db.scalar(select(Annotator).where(Annotator.email == ANNOTATOR_EMAIL))
    if ann is None:
        ann = Annotator(
            kind="human",
            display_name="Demo Annotator",
            email=ANNOTATOR_EMAIL,
            user_id=user.id,
            status="active",
            reputation_score=1.0,
        )
        db.add(ann)
        db.flush()
    return ann


def _template(db, name: str) -> Template:
    return db.scalar(
        select(Template)
        .where(Template.name == name, Template.kind == "builtin")
        .order_by(Template.version.desc())
    )


def _make_project(db, *, template_name, name, k, guidelines, units_jsonl) -> Project | None:
    if db.scalar(select(Project).where(Project.name == name)) is not None:
        return None  # already created on a previous run
    tmpl = _template(db, template_name)
    if tmpl is None:
        raise RuntimeError(f"template '{template_name}' not seeded")
    project = create_project(
        db,
        name=name,
        template_id=tmpl.id,
        labels_per_unit=k,
        gold_ratio=0.0,  # keep the demo simple: no gold injection
        guidelines_md=guidelines,
    )
    ingest_units(db, project, parse_jsonl(units_jsonl), batch_name="demo")
    return project


def main() -> None:
    db = SessionLocal()
    try:
        seed_templates(db)
        admin = _get_or_create_admin(db)
        annotator = _get_or_create_annotator(db, admin)

        projects = []
        for spec in (
            {
                "template_name": "image-classification",
                "name": "Demo — Image classification",
                "k": 1,
                "guidelines": "Pick the label that best describes each image. "
                "Use **Other** if none fit.",
                "units_jsonl": IMAGE_UNITS,
            },
            {
                "template_name": "text-sentiment",
                "name": "Demo — Text sentiment",
                "k": 1,
                "guidelines": "Judge the overall sentiment, then rate your confidence.",
                "units_jsonl": SENTIMENT_UNITS,
            },
            {
                "template_name": "side-by-side-preference",
                "name": "Demo — Side-by-side preference",
                "k": 2,  # divisible by the 2 panel_order variants (§2.7)
                "guidelines": "Pick the more helpful response. Press **Tie** if they're equal.",
                "units_jsonl": SIDE_BY_SIDE_UNITS,
            },
        ):
            p = _make_project(db, **spec)
            if p is not None:
                projects.append(p)

        # Re-list all demo projects (including any from prior runs) for the summary.
        all_demo = db.scalars(select(Project).where(Project.name.like("Demo — %"))).all()
        db.commit()

        print("\n=== MiniLP demo ready ===")
        print(f"Admin API key : {ADMIN_API_KEY}   (user {admin.email}, role admin)")
        print(f"Annotator id  : {annotator.id}   ({annotator.display_name})")
        print("\nOpen any of these in your browser:\n")
        for p in all_demo:
            print(f"  {p.name}")
            print(
                f"    http://localhost:5173/?project={p.id}"
                f"&annotator={annotator.id}&key={ADMIN_API_KEY}\n"
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()

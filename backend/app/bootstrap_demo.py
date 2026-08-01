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
from app.models import Annotator, JudgeConfig, Project, Template, User
from app.services.active_learning import register_checkpoint
from app.services.auth.roles import hash_api_key
from app.services.ingest.bulk import ingest_units, parse_jsonl
from app.services.judges import attach_judge, create_judge_config, run_judge
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


# --- M4 quality demo (§6) ---------------------------------------------------
# Half the units are golds expecting "cat", with a deliberately twitchy threshold
# (70% over a 4-gold window, acting after 3) so a few wrong answers demonstrate
# the pause-and-void path in under a minute. K=2 with a 0.9 consensus requirement
# and grow_then_escalate makes the growth/escalation path just as quick to reach.
# NOTE: gold and regular payloads must be indistinguishable to the annotator
# (§6.1) — identical context text, same image host. Gold identity lives ONLY in
# the (server-side) is_gold / gold_expected fields. To find out which demo units
# are golds, ask the DB as an admin:
#   SELECT id, is_gold FROM units WHERE project_id = <quality project id>;
QUALITY_UNITS = "\n".join(
    json.dumps(row)
    for row in (
        [
            {
                "payload": {
                    "image_url": f"https://placekitten.com/{500 + i}/400",
                    "context": "a sample photo",
                },
                "is_gold": True,
                "gold_expected": {"category": "cat"},
            }
            for i in range(6)
        ]
        + [
            {
                "payload": {
                    "image_url": f"https://placekitten.com/{400 + i}/300",
                    "context": "a sample photo",
                }
            }
            for i in range(1, 5)
        ]
    )
)

# --- M6 palette demo (§2.1) -------------------------------------------------
# The rubric template exercises every field type the visual builder can drop:
# rating, slider, dropdown, tags, ranking, yes/no, date. Clone it in the builder
# (#/admin/templates) to see the palette on a task that plausibly wants all of it.
RUBRIC_UNITS = _jsonl(
    [
        {
            "content": "## Refund policy\n\nItems may be returned within 30 days. "
            "Shipping is refunded only if the item arrived damaged.",
            "context": "Help-centre article draft",
        },
        {
            "content": "# Getting started\n\nInstall the CLI, run `init`, then `deploy`. "
            "That's it — you're live.",
            "context": "Docs quickstart",
        },
        {
            "content": "Our new plan is *literally* the best thing ever and everyone "
            "should switch immediately!!!",
            "context": "Marketing email draft",
        },
    ]
)

QUALITY_CONFIG = {
    "quality": {
        "gold_threshold": 0.7,
        "gold_window": 4,
        "gold_min_samples": 3,
        "void_lookback": 20,
        "on_disagreement": "grow_then_escalate",
    }
}

# --- M8 ensemble demo (§7.2) ------------------------------------------------
# A project built so that one `judges:run` lands the review queue populated.
#
# Three deliberate settings:
#   K = max_K = 2       — no room to grow, so disagreement escalates *now*
#                         rather than opening slots no judge is allowed to fill
#                         (the annotator-unit exclusion, §2.7, means each judge
#                         votes once per unit).
#   min_consensus 0.9   — two judges answering differently can never clear it.
#   gold_threshold 0    — the golds here are for *calibration*, not policing:
#                         they give the two judges genuinely different
#                         reputations, which is what makes the weighted merge
#                         visibly prefer one of them. The pause cliff is
#                         demonstrated by the quality project instead.
ENSEMBLE_UNITS = "\n".join(
    json.dumps(row)
    for row in (
        [
            {
                "payload": {
                    "image_url": f"https://placekitten.com/{600 + i}/420",
                    "context": "a sample photo",
                },
                "is_gold": True,
                "gold_expected": {"category": "cat"},
            }
            for i in range(3)
        ]
        + [
            {
                "payload": {
                    "image_url": f"https://placekitten.com/{700 + i}/420",
                    "context": "a sample photo",
                }
            }
            for i in range(5)
        ]
    )
)

ENSEMBLE_CONFIG = {
    "quality": {"gold_threshold": 0.0, "gold_window": 8, "on_disagreement": "escalate"},
    "review": {"backlog_threshold": 5},
}


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


def _make_project(
    db,
    *,
    template_name,
    name,
    k,
    guidelines,
    units_jsonl,
    gold_ratio=0.0,  # most demo projects keep it simple: no gold injection
    max_k=None,
    agreement=None,
    config=None,
) -> Project | None:
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
        max_labels_per_unit=max_k,
        gold_ratio=gold_ratio,
        guidelines_md=guidelines,
        agreement=agreement,
        config=config,
    )
    ingest_units(db, project, parse_jsonl(units_jsonl), batch_name="demo")
    return project


# --- M7 judge demo (§7.1) ---------------------------------------------------
# The demo enrolls a judge on the side-by-side project but does NOT run it: the
# Judges tab lands populated, with "Dry run" and "Run" one click away, so the
# orchestrator is discoverable without anyone spending money or pasting a key.
#
# The provider is ``mock`` — a real provider class (app/services/judges/providers/
# mock.py), deterministic and free. Swapping it for a paid one is two fields on
# the same form: provider + model, with the API key read from an environment
# variable the server names, never from the database.
DEMO_JUDGE_NAME = "demo-mock-judge"


def _get_or_create_demo_judge(db, project: Project | None) -> JudgeConfig | None:
    """Enroll a mock judge on ``project``. Idempotent across re-runs."""
    if project is None:
        return None
    config = db.scalar(select(JudgeConfig).where(JudgeConfig.name == DEMO_JUDGE_NAME))
    if config is None:
        config = create_judge_config(
            db,
            name=DEMO_JUDGE_NAME,
            provider="mock",
            model_id="mock-1",
            params={"temperature": 0.0, "max_tokens": 512},
            prompt_template=(
                "You are grading two candidate answers for helpfulness and accuracy.\n"
                "Judge only what is in front of you; do not assume which came from "
                "which system."
            ),
            # A cap low enough that the demo *reaches* it on the first run: the
            # side-by-side project has 3 units and one judge may label each once,
            # so a 2-label cap stops the run one unit short and fires
            # budget.cap_reached (§7.3). Seeing the hard stop is the point.
            budget={"max_labels": 2, "project_usd": 1.0},
        )
    attach_judge(db, project.id, config.id)
    return config


# Two judges that answer *differently*. One run over the ensemble project and
# every unit has two disagreeing votes, so the default pipeline cannot
# auto-finalize any of them and the review queue lands populated — which is the
# only way "escalate on disagreement" is demonstrable by one person: the
# annotator-unit exclusion (§2.7) means you cannot disagree with yourself.
#
# Their answers are pinned rather than hashed so the disagreement is guaranteed
# and the reputation gap is real: the golds on that project expect "cat", so the
# ensemble also shows a well-calibrated judge outweighing a poorly calibrated one
# — which is what "calibration-weighted merge" means (§7.2).
ENSEMBLE_JUDGES = (("demo-judge-cat", "cat"), ("demo-judge-dog", "dog"))


def _get_or_create_ensemble(db, project: Project | None) -> list[JudgeConfig]:
    if project is None:
        return []
    configs = []
    for name, answer in ENSEMBLE_JUDGES:
        config = db.scalar(select(JudgeConfig).where(JudgeConfig.name == name))
        if config is None:
            config = create_judge_config(
                db,
                name=name,
                provider="mock",
                model_id="mock-1",
                params={
                    "temperature": 0.0,
                    "max_tokens": 256,
                    "mock": {
                        "answers": {"category": answer},
                        "reasoning": f"Pinned demo judgment: always answers '{answer}'.",
                    },
                },
                prompt_template="Classify the image into one of the given categories.",
            )
        attach_judge(db, project.id, config.id)
        configs.append(config)
    return configs


# --- M9 active-learning demo (§8) -------------------------------------------
# "Demo: scripted loop with a toy student model improving over 3 iterations"
# (§12). ``demo-student`` is a mock judge re-enrolled three times under the
# same name — each ``register_checkpoint`` call is exactly §8 step 4
# ("re-enroll"), and each version's *pinned* answer is deliberately wrong on a
# shrinking share of a fixed gold distribution (1 bird, 2 dog, 3 cat per
# batch), so gold accuracy climbs on hard numbers: 1/6 -> 2/6 -> 3/6. A real
# loop would fine-tune between iterations instead of relabeling by hand; the
# mechanism this demonstrates — register the next checkpoint, watch its eval
# curve — is identical either way.
AL_GOLD_DISTRIBUTION = ("bird", "dog", "dog", "cat", "cat", "cat")
AL_PROJECT_NAME = "Demo — Active-learning loop"
AL_JUDGE_NAME = "demo-student"
AL_ITERATIONS = ("bird", "dog", "cat")  # each version's pinned (and improving) answer

# gold_threshold=0: the pause-and-void cliff (§6.1) exists for real annotators
# below a quality bar, and would otherwise void the deliberately-imperfect
# early checkpoints' labels out from under their own eval curve.
AL_CONFIG = {"quality": {"gold_threshold": 0.0}}


def _al_batch_units(batch: int) -> str:
    return "\n".join(
        json.dumps(
            {
                "payload": {
                    "image_url": f"https://placekitten.com/{800 + batch * 10 + i}/400",
                    "context": "a sample photo",
                },
                "is_gold": True,
                "gold_expected": {"category": answer},
            }
        )
        for i, answer in enumerate(AL_GOLD_DISTRIBUTION)
    )


def _get_or_create_al_loop_demo(db) -> Project | None:
    """Idempotent: on a re-run, the project (and its three checkpoints) already
    exist and nothing here repeats the labeling."""
    existing = db.scalar(select(Project).where(Project.name == AL_PROJECT_NAME))
    if existing is not None:
        return existing

    tmpl = _template(db, "image-classification")
    if tmpl is None:
        return None
    project = create_project(
        db,
        name=AL_PROJECT_NAME,
        template_id=tmpl.id,
        labels_per_unit=1,
        gold_ratio=1.0,
        config=AL_CONFIG,
        guidelines_md="A toy student model relabels three fresh batches of the "
        "same gold mix (1 bird, 2 dog, 3 cat), one checkpoint per batch. Its "
        "pinned answer changes each time, so gold accuracy climbs 1/6 -> 2/6 -> "
        "3/6 across the three registered checkpoints (M9, §8).",
    )
    for batch_index, answer in enumerate(AL_ITERATIONS):
        units = parse_jsonl(_al_batch_units(batch_index))
        ingest_units(db, project, units, batch_name=f"al-v{batch_index + 1}")
        ckpt = register_checkpoint(
            db,
            project.id,
            name=AL_JUDGE_NAME,
            provider="mock",
            model_id=f"demo-student-ckpt-{answer}",
            params={
                "mock": {
                    "answers": {"category": answer},
                    "reasoning": f"Pinned demo checkpoint: always answers '{answer}'.",
                }
            },
        )
        run_judge(db, project.id, ckpt["judge_config_id"], limit=len(AL_GOLD_DISTRIBUTION))
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
            {
                "template_name": "content-review-rubric",
                "name": "Demo — Content review rubric (M6 palette)",
                "k": 1,
                "guidelines": "Rate the draft, then say whether it needs a human "
                "reviewer. Every field type the **visual builder** offers is on this "
                "form: stars, a slider, a dropdown, tags, a drag-to-order ranking, a "
                "yes/no and a date. All of it is keyboard-reachable — press `?`.",
                "units_jsonl": RUBRIC_UNITS,
            },
            {
                "template_name": "image-classification",
                "name": "Demo — Quality (golds + consensus)",
                "k": 2,
                "max_k": 4,
                "gold_ratio": 0.5,
                "agreement": {"category": {"match": "exact", "min_consensus": 0.9}},
                "config": QUALITY_CONFIG,
                "guidelines": "Half of these are gold questions expecting **cat**. "
                "Answer three of them wrong and you will be paused (M4, §6.1).",
                "units_jsonl": QUALITY_UNITS,
            },
            {
                "template_name": "image-classification",
                "name": "Demo — Ensemble + review queue",
                "k": 2,
                "max_k": 2,  # no room to grow: disagreement escalates immediately
                "gold_ratio": 0.4,
                "agreement": {"category": {"match": "exact", "min_consensus": 0.9}},
                "config": ENSEMBLE_CONFIG,
                "guidelines": "Two model judges vote on every unit and always "
                "disagree, so nothing here can auto-finalize. Run them, then open "
                "the **review queue** to approve or override the merged proposal "
                "(M8, §7.2).",
                "units_jsonl": ENSEMBLE_UNITS,
            },
        ):
            p = _make_project(db, **spec)
            if p is not None:
                projects.append(p)

        # Build the AL-loop demo *before* the summary re-list below, so its
        # project shows up in the per-project URL list along with everything else.
        al_loop = _get_or_create_al_loop_demo(db)

        # Re-list all demo projects (including any from prior runs) for the summary.
        all_demo = db.scalars(select(Project).where(Project.name.like("Demo — %"))).all()
        judged = next((p for p in all_demo if "Side-by-side" in p.name), None)
        judge = _get_or_create_demo_judge(db, judged)
        ensembled = next((p for p in all_demo if "Ensemble" in p.name), None)
        ensemble = _get_or_create_ensemble(db, ensembled)
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
        print("Annotator home — every project with the work waiting in it (M8, §11):\n")
        print(f"  http://localhost:5173/?annotator={annotator.id}&key={ADMIN_API_KEY}\n")
        if ensemble and ensembled is not None:
            print("Ensembles + review queue (M8, §7.2) — two judges that disagree:\n")
            print(
                f"  1. Fill it : curl -X POST -H 'Authorization: Bearer {ADMIN_API_KEY}' "
                f"-H 'Content-Type: application/json' "
                f"-d '{{}}' localhost:8000/projects/{ensembled.id}/judges:run"
            )
            print(
                f"  2. Review  : http://localhost:5173/?review=1"
                f"&annotator={annotator.id}&key={ADMIN_API_KEY}"
            )
            print(
                f"     Policy  : curl -H 'Authorization: Bearer {ADMIN_API_KEY}' "
                f"localhost:8000/projects/{ensembled.id}/pipeline\n"
            )
        if al_loop is not None:
            print(
                "Active-learning loop (M9, §8) — a toy student model, three "
                "checkpoints already run, gold accuracy 1/6 -> 2/6 -> 3/6:\n"
            )
            print(
                f"  Eval curve : curl -H 'Authorization: Bearer {ADMIN_API_KEY}' "
                f"'localhost:8000/projects/{al_loop.id}/active-learning/iterations"
                f"?name={AL_JUDGE_NAME}' | python -m json.tool"
            )
            print(
                f"  Next batch : curl -H 'Authorization: Bearer {ADMIN_API_KEY}' "
                f"'localhost:8000/projects/{al_loop.id}/active-learning/batch'"
            )
            print(
                "  Iterate    : curl -X POST -H "
                f"'Authorization: Bearer {ADMIN_API_KEY}' -H 'Content-Type: application/json' -d "
                '\'{"name": "demo-student", "provider": "mock", "model_id": "ckpt-4", '
                '"params": {"mock": {"answers": {"category": "cat"}}}}\' '
                f"localhost:8000/projects/{al_loop.id}/active-learning/checkpoints:register\n"
            )
        print("Admin surface (progress · bias · configure · add tasks · export):\n")
        print(f"  http://localhost:5173/#/admin?key={ADMIN_API_KEY}")
        print(
            f"  http://localhost:5173/#/admin/templates?key={ADMIN_API_KEY}   (gallery + builder)"
        )
        print(
            f"  http://localhost:5173/#/admin/templates/new?key={ADMIN_API_KEY}"
            "   (build a template from scratch)\n"
        )
        print("Quality endpoints (M4) for the annotator above:\n")
        print(
            f"  curl -H 'Authorization: Bearer {ADMIN_API_KEY}' "
            f"localhost:8000/annotators/{annotator.id}/report\n"
        )
        if judge is not None and judged is not None:
            print("Model judges (M7, §7.1) — a mock judge is enrolled, not yet run:\n")
            print(
                f"  Judges tab : http://localhost:5173/#/admin/project/{judged.id}?key={ADMIN_API_KEY}"
            )
            print(
                f"  Dry run    : curl -X POST -H 'Authorization: Bearer {ADMIN_API_KEY}' "
                f"-H 'Content-Type: application/json' "
                f"-d '{{\"dry_run\": true}}' localhost:8000/projects/{judged.id}/judges:run"
            )
            print(
                f"  Live run   : curl -X POST -H 'Authorization: Bearer {ADMIN_API_KEY}' "
                f"-H 'Content-Type: application/json' "
                f"-d '{{}}' localhost:8000/projects/{judged.id}/judges:run"
            )
            print(
                f"  Costs      : curl -H 'Authorization: Bearer {ADMIN_API_KEY}' "
                f"localhost:8000/projects/{judged.id}/analytics/costs\n"
            )
        if all_demo:
            print("Export (M6, §10):\n")
            print(
                f"  curl -H 'Authorization: Bearer {ADMIN_API_KEY}' "
                f"'localhost:8000/projects/{all_demo[0].id}/export?format=labels'\n"
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()

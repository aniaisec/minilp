"""Seed the gallery built-in templates into the configured database.

Usage (after ``alembic upgrade head``):
    python -m app.seed
"""

from app.db import SessionLocal
from app.services.templates.seed import seed_templates


def main() -> None:
    db = SessionLocal()
    try:
        created = seed_templates(db)
        db.commit()
        print(f"Seeded {len(created)} gallery templates:")
        for t in created:
            print(f"  - {t.name} v{t.version} ({t.kind})")
    finally:
        db.close()


if __name__ == "__main__":
    main()

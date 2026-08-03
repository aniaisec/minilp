"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api import (
    active_learning,
    analytics,
    annotators,
    judges,
    marketplace,
    me,
    projects,
    review,
    tasks,
    templates,
    units,
    webhooks,
)

app = FastAPI(
    title="MiniLP",
    description="Mini labeling platform - configurable human and model labeling",
    version="0.1.0",
)

app.include_router(templates.router)
app.include_router(projects.router)
app.include_router(units.router)
app.include_router(tasks.router)
app.include_router(annotators.router)
app.include_router(analytics.router)
app.include_router(judges.router)
app.include_router(me.router)
app.include_router(review.router)
app.include_router(webhooks.router)
app.include_router(active_learning.router)
app.include_router(marketplace.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

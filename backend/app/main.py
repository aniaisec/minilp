"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api import projects, templates

app = FastAPI(
    title="MiniLP",
    description="Mini labeling platform - configurable human and model labeling",
    version="0.1.0",
)

app.include_router(templates.router)
app.include_router(projects.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

"""FastAPI application entry point."""

from fastapi import FastAPI

app = FastAPI(
    title="MiniLP",
    description="Mini labeling platform for pairwise preference judgments",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

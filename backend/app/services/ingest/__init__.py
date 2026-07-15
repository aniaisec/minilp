"""Bulk unit ingest with per-row validation and slot pre-generation (§5, M1)."""

from app.services.ingest.bulk import RowResult, ingest_report, ingest_units

__all__ = ["RowResult", "ingest_report", "ingest_units"]

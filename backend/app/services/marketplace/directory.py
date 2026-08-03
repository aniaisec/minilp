"""The local shared-bundle directory (§12, M10) — "a local directory of shared
bundles ships with the repo — no hosted registry in v1."

Every ``.json`` file directly under ``bundles/`` is a marketplace bundle, loaded
and validated shape-only at read time (the real validation happens on import, via
``import_bundle`` — reading the directory must never fail because one file in it
is a bundle for a bundle_version this instance doesn't understand yet).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BUNDLES_DIR = Path(__file__).parent / "bundles"


class LocalBundleError(ValueError):
    """A requested local bundle file doesn't exist or isn't a bundle."""


def _safe_filename(filename: str) -> Path:
    """Resolve ``filename`` inside ``BUNDLES_DIR``, refusing path traversal.

    ``filename`` comes off the URL path (``GET /marketplace/bundles/{filename}``),
    so ``../../etc/passwd`` is a real input, not a hypothetical one.
    """
    if not filename or "/" in filename or "\\" in filename or filename in (".", ".."):
        raise LocalBundleError(f"invalid bundle filename {filename!r}")
    path = (BUNDLES_DIR / filename).resolve()
    if path.parent != BUNDLES_DIR.resolve() or not path.name.endswith(".json"):
        raise LocalBundleError(f"invalid bundle filename {filename!r}")
    return path


def list_local_bundles() -> list[dict[str, Any]]:
    """Metadata for every shipped bundle — the marketplace browser's listing."""
    out: list[dict[str, Any]] = []
    if not BUNDLES_DIR.is_dir():
        return out
    for path in sorted(BUNDLES_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        out.append(
            {
                "filename": path.name,
                "kind": data.get("kind"),
                "name": data.get("name"),
                "description": data.get("description"),
                "bundle_version": data.get("bundle_version"),
            }
        )
    return out


def read_local_bundle(filename: str) -> dict[str, Any]:
    """The full bundle document for one shipped file."""
    path = _safe_filename(filename)
    if not path.is_file():
        raise LocalBundleError(f"no local bundle named {filename!r}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise LocalBundleError(f"bundle {filename!r} is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise LocalBundleError(f"bundle {filename!r} must be a JSON object")
    return data


__all__ = ["BUNDLES_DIR", "LocalBundleError", "list_local_bundles", "read_local_bundle"]

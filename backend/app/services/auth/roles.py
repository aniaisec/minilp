"""API-key hashing + role-hierarchy helpers (pure; no FastAPI, no DB).

Kept framework-free so the rules are unit-testable in isolation. FastAPI wiring
(header parsing, DB lookup, 401/403) lives in ``app/api/deps.py``.
"""

from __future__ import annotations

import hashlib

# Role hierarchy (higher rank implies every lower capability). §5:
#   admin    — templates / projects / judges / webhooks
#   reviewer — review queue / finalize (+ everything an annotator can do)
#   annotator— /tasks/* (incl. judge workers as service users)
ROLE_RANK: dict[str, int] = {"annotator": 1, "reviewer": 2, "admin": 3}


class AuthError(Exception):
    """Raised for authentication/authorization failures.

    ``status`` mirrors the HTTP code the API layer should surface: 401 when the
    caller is unauthenticated, 403 when authenticated but under-privileged.
    """

    def __init__(self, message: str, *, status: int = 401) -> None:
        super().__init__(message)
        self.status = status


def hash_api_key(raw_key: str) -> str:
    """Deterministically hash a plaintext API key for storage/comparison.

    SHA-256 hex (64 chars, fits ``users.api_key_hash`` String(128)). Keys are
    never stored in the clear; lookups hash the presented key and match on the
    hash column.
    """
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def role_allowed(user_role: str, allowed: set[str]) -> bool:
    """True if ``user_role`` satisfies any role in ``allowed``.

    A role satisfies an allowed role when its rank is >= that role's rank, so
    listing ``{"annotator"}`` also admits reviewers and admins, while
    ``{"admin"}`` admits only admins.
    """
    if user_role not in ROLE_RANK:
        return False
    min_required = min(ROLE_RANK[r] for r in allowed if r in ROLE_RANK)
    return ROLE_RANK[user_role] >= min_required

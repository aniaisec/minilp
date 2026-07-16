"""Auth subsystem (§5): API-key authentication + role gating.

Every ``user`` carries an API key (stored as a hash) and a ``role``
(``admin`` / ``reviewer`` / ``annotator``). Endpoints declare the roles they
accept; the dependency looks up the presenting key, resolves the user, and
enforces the role. ``admin`` > ``reviewer`` > ``annotator`` for convenience, but
each endpoint states its own accepted set explicitly.
"""

from app.services.auth.roles import (
    ROLE_RANK,
    AuthError,
    hash_api_key,
    role_allowed,
)

__all__ = [
    "ROLE_RANK",
    "AuthError",
    "hash_api_key",
    "role_allowed",
]

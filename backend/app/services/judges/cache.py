"""Judge response cache (§4: "identical calls are never paid for twice").

The key is §4's: ``(judge_config_id + prompt_version, unit_id, variant)``. What
makes it *correct* rather than merely fast is what it deliberately does not
collapse:

- **variant is part of the key.** The same unit shown "AB" and "BA" is two
  different questions, and answering the second from the first's cache would
  fabricate perfect order-consistency — destroying §9's headline metric while
  looking like a cost saving.
- **prompt version is part of the key.** A new prompt is a new judge (§7.1).
- **the prompt hash is checked, not keyed.** If the assembled text changed while
  the version did not, we treat it as a miss. A cache that answers from a prompt
  nobody sent is not a cache.

Cache hits still produce a real label with ``cache_hit=True`` and ``cost_usd=0``,
so `$/label` in §5's cost analytics reflects what was actually paid.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import JudgeCacheEntry


@dataclass(frozen=True)
class CacheKey:
    judge_config_id: int
    prompt_version: int
    unit_id: int
    variant_key: str


def lookup(db: Session, key: CacheKey, prompt_hash: str) -> JudgeCacheEntry | None:
    """Return the cached response, or None on a miss or a prompt-hash mismatch."""
    entry = db.scalar(
        select(JudgeCacheEntry).where(
            JudgeCacheEntry.judge_config_id == key.judge_config_id,
            JudgeCacheEntry.prompt_version == key.prompt_version,
            JudgeCacheEntry.unit_id == key.unit_id,
            JudgeCacheEntry.variant_key == key.variant_key,
        )
    )
    if entry is None or entry.prompt_hash != prompt_hash:
        return None
    return entry


def store(
    db: Session,
    key: CacheKey,
    *,
    prompt_hash: str,
    response_text: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_usd: float = 0.0,
) -> JudgeCacheEntry:
    """Insert or refresh the entry for a key."""
    entry = db.scalar(
        select(JudgeCacheEntry).where(
            JudgeCacheEntry.judge_config_id == key.judge_config_id,
            JudgeCacheEntry.prompt_version == key.prompt_version,
            JudgeCacheEntry.unit_id == key.unit_id,
            JudgeCacheEntry.variant_key == key.variant_key,
        )
    )
    if entry is None:
        entry = JudgeCacheEntry(
            judge_config_id=key.judge_config_id,
            prompt_version=key.prompt_version,
            unit_id=key.unit_id,
            variant_key=key.variant_key,
            prompt_hash=prompt_hash,
            response_text=response_text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
        )
        db.add(entry)
    else:
        entry.prompt_hash = prompt_hash
        entry.response_text = response_text
        entry.tokens_in = tokens_in
        entry.tokens_out = tokens_out
        entry.cost_usd = cost_usd
    db.flush()
    return entry

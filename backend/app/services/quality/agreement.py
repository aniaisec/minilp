"""Inter-annotator agreement metrics (§6.3).

Cohen's kappa (exactly two raters) and Fleiss' kappa (K > 2), computed **per input
key** on canonical values, plus per-unit vote entropy which separates genuinely
ambiguous units from noisy raters (and drives escalation, §7.2, and active
learning, §8).

All functions here are pure — they take vote tables, not a database — so the
hand-computed fixtures in the tests pin the arithmetic, not the plumbing. The
DB-facing wrapper (``project_agreement``) lives at the bottom and only assembles
those tables.

Category derivation honors the per-key match rule: an ``exact`` key buckets on the
value itself, a ``within``/``jaccard`` key is not an equivalence relation so kappa
is computed on exact categories and the tolerance shows up in the consensus rate
instead (§6.4) — reporting a kappa over non-transitive "agreement" would be
arithmetic nonsense, and we say so rather than inventing a number.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Annotator, Label, Project, Unit
from app.services.quality.matching import _hashable


@dataclass
class KappaResult:
    """A kappa figure plus the observed/expected agreement it came from."""

    kappa: float | None
    observed: float | None
    expected: float | None
    n_items: int
    n_categories: int
    method: str  # "cohen" | "fleiss" | "none"

    def as_dict(self) -> dict[str, Any]:
        return {
            "kappa": self.kappa,
            "observed_agreement": self.observed,
            "expected_agreement": self.expected,
            "n_items": self.n_items,
            "n_categories": self.n_categories,
            "method": self.method,
        }


_EMPTY = KappaResult(None, None, None, 0, 0, "none")


def cohens_kappa(pairs: list[tuple[Any, Any]]) -> KappaResult:
    """Cohen's kappa for two raters over ``pairs`` of (rater A, rater B) labels.

    κ = (Po − Pe) / (1 − Pe). When both raters are in perfect agreement *and*
    used a single category, Pe == 1 and κ is undefined — reported as ``None``
    rather than a fabricated 1.0 or a ZeroDivisionError.
    """
    pairs = [(_hashable(a), _hashable(b)) for a, b in pairs]
    n = len(pairs)
    if n == 0:
        return _EMPTY

    categories = {c for pair in pairs for c in pair}
    observed = sum(1 for a, b in pairs if a == b) / n

    count_a = Counter(a for a, _ in pairs)
    count_b = Counter(b for _, b in pairs)
    expected = sum((count_a[c] / n) * (count_b[c] / n) for c in categories)

    if math.isclose(expected, 1.0):
        return KappaResult(None, observed, expected, n, len(categories), "cohen")
    kappa = (observed - expected) / (1 - expected)
    return KappaResult(kappa, observed, expected, n, len(categories), "cohen")


def fleiss_kappa(item_ratings: list[list[Any]]) -> KappaResult:
    """Fleiss' kappa for a fixed number of raters per item (K > 2).

    ``item_ratings`` is one list of categorical ratings per item. Items whose
    rater count differs from the modal count are dropped: Fleiss' formula assumes
    a constant n per item, and silently mixing counts biases Pe. Items with fewer
    than two ratings carry no agreement information and are dropped too.
    """
    ratings = [[_hashable(v) for v in item] for item in item_ratings if len(item) >= 2]
    if not ratings:
        return _EMPTY

    modal_n = Counter(len(item) for item in ratings).most_common(1)[0][0]
    ratings = [item for item in ratings if len(item) == modal_n]
    n_items = len(ratings)
    if n_items == 0 or modal_n < 2:
        return _EMPTY

    categories = sorted({c for item in ratings for c in item}, key=repr)
    n_cat = len(categories)

    # P_i: agreement among rater pairs within item i.
    p_items = []
    for item in ratings:
        counts = Counter(item)
        p_items.append((sum(c * c for c in counts.values()) - modal_n) / (modal_n * (modal_n - 1)))
    observed = sum(p_items) / n_items

    # p_j: marginal proportion of each category across all ratings.
    total_ratings = n_items * modal_n
    marginals = Counter(c for item in ratings for c in item)
    expected = sum((marginals[c] / total_ratings) ** 2 for c in categories)

    if math.isclose(expected, 1.0):
        return KappaResult(None, observed, expected, n_items, n_cat, "fleiss")
    kappa = (observed - expected) / (1 - expected)
    return KappaResult(kappa, observed, expected, n_items, n_cat, "fleiss")


def kappa(item_ratings: list[list[Any]]) -> KappaResult:
    """Dispatch to Cohen (every item has exactly 2 ratings) or Fleiss (K > 2)."""
    usable = [item for item in item_ratings if len(item) >= 2]
    if not usable:
        return _EMPTY
    if all(len(item) == 2 for item in usable):
        return cohens_kappa([(item[0], item[1]) for item in usable])
    return fleiss_kappa(usable)


def vote_entropy(values: list[Any], *, normalized: bool = True) -> float:
    """Shannon entropy of a unit's votes for one key.

    0.0 = unanimous. Normalized by log(k) over the *observed* category count so
    it lands in [0, 1] and is comparable across keys with different option
    counts; a single observed category yields 0.0.
    """
    if not values:
        return 0.0
    counts = Counter(_hashable(v) for v in values)
    total = len(values)
    entropy = -sum((c / total) * math.log(c / total) for c in counts.values())
    if not normalized:
        return entropy
    k = len(counts)
    if k <= 1:
        return 0.0
    return entropy / math.log(k)


# --- DB-facing assembly -----------------------------------------------------


def _label_rows(
    db: Session, project_id: int, kinds: tuple[str, ...] | None = None
) -> list[tuple[int, int, str, dict[str, Any]]]:
    """(unit_id, annotator_id, annotator_kind, value) for valid labels."""
    stmt = (
        select(Label.unit_id, Label.annotator_id, Annotator.kind, Label.value)
        .join(Unit, Label.unit_id == Unit.id)
        .join(Annotator, Label.annotator_id == Annotator.id)
        .where(Unit.project_id == project_id, Label.is_valid.is_(True))
    )
    if kinds:
        stmt = stmt.where(Annotator.kind.in_(kinds))
    return [tuple(r) for r in db.execute(stmt).all()]


def _ratings_by_key(
    rows: list[tuple[int, int, str, dict[str, Any]]],
) -> dict[str, dict[int, list[Any]]]:
    """{input key: {unit_id: [value, ...]}}."""
    out: dict[str, dict[int, list[Any]]] = defaultdict(lambda: defaultdict(list))
    for unit_id, _annotator_id, _kind, value in rows:
        for key, val in (value or {}).items():
            out[key][unit_id].append(val)
    return {k: dict(v) for k, v in out.items()}


def project_agreement(db: Session, project_id: int, *, group: str = "all") -> dict[str, Any]:
    """Per-key kappa + entropy for a project (§6.3, §5 analytics/agreement).

    ``group``: ``all`` | ``human`` | ``model`` | ``cross``. ``cross`` pairs each
    unit's human majority against its judge majority — the human-vs-judge figure
    §6.3 calls the interesting research artifact (empty until M7 enrolls judges).
    """
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError(f"project {project_id} not found")

    if group == "cross":
        return _cross_agreement(db, project_id)

    kinds = {"human": ("human",), "model": ("model",)}.get(group)
    rows = _label_rows(db, project_id, kinds)
    by_key = _ratings_by_key(rows)

    keys: dict[str, Any] = {}
    for key, per_unit in sorted(by_key.items()):
        item_ratings = [v for v in per_unit.values() if len(v) >= 2]
        result = kappa(item_ratings)
        entropies = [vote_entropy(v) for v in per_unit.values() if len(v) >= 2]
        keys[key] = {
            **result.as_dict(),
            "mean_entropy": (sum(entropies) / len(entropies)) if entropies else None,
            "units_with_multiple_labels": len(item_ratings),
        }

    return {
        "project_id": project_id,
        "group": group,
        "labels_per_unit": project.labels_per_unit,
        "keys": keys,
    }


def _majority(values: list[Any]) -> Any | None:
    """Most common value, or None on an empty list / tie at the top."""
    if not values:
        return None
    counts = Counter(_hashable(v) for v in values).most_common()
    if len(counts) > 1 and counts[0][1] == counts[1][1]:
        return None
    return counts[0][0]


def _cross_agreement(db: Session, project_id: int) -> dict[str, Any]:
    human = _ratings_by_key(_label_rows(db, project_id, ("human",)))
    model = _ratings_by_key(_label_rows(db, project_id, ("model",)))

    keys: dict[str, Any] = {}
    for key in sorted(set(human) | set(model)):
        pairs: list[tuple[Any, Any]] = []
        for unit_id, human_votes in human.get(key, {}).items():
            model_votes = model.get(key, {}).get(unit_id)
            if not model_votes:
                continue
            h, m = _majority(human_votes), _majority(model_votes)
            if h is None or m is None:  # unresolved tie on either side
                continue
            pairs.append((h, m))
        keys[key] = {
            **cohens_kappa(pairs).as_dict(),
            "mean_entropy": None,
            "units_with_multiple_labels": len(pairs),
        }

    return {"project_id": project_id, "group": "cross", "keys": keys}

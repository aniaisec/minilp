"""Pure analytics arithmetic (§9, §11) — no database, hand-checkable fixtures.

The Wilson interval and throughput formula are the two numbers the API reports
that a reader is most likely to sanity-check, so they get worked examples here
the same way the kappa fixtures do in ``test_quality_agreement``.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.services.analytics.progress import throughput
from app.services.analytics.stats import bias_score, token, wilson_interval

# --- Wilson interval --------------------------------------------------------


def test_wilson_centered_on_a_fair_split():
    """8/16 → estimate 0.5, symmetric interval strictly inside (0, 1)."""
    r = wilson_interval(8, 16)
    assert r.estimate == pytest.approx(0.5)
    assert 0.0 < r.low < 0.5 < r.high < 1.0
    # Symmetry about 0.5 for a balanced count.
    assert (0.5 - r.low) == pytest.approx(r.high - 0.5, abs=1e-9)


def test_wilson_worked_example_ten_of_ten():
    """All-success stays below 1.0 (the point of Wilson over Wald).

    p=1, z=1.96, n=10: center = (1 + z²/20) / (1 + z²/10) = 0.8278…,
    and the upper bound is < 1.
    """
    r = wilson_interval(10, 10)
    assert r.estimate == 1.0
    assert r.high < 1.0
    assert r.low == pytest.approx(0.7225, abs=1e-3)


def test_wilson_empty_is_maximally_uninformative():
    r = wilson_interval(0, 0)
    assert (r.estimate, r.low, r.high, r.n) == (0.5, 0.0, 1.0, 0)


def test_wider_interval_for_smaller_n():
    narrow = wilson_interval(50, 100)
    wide = wilson_interval(5, 10)
    assert (wide.high - wide.low) > (narrow.high - narrow.low)


# --- bias score -------------------------------------------------------------


def test_bias_score_is_zero_on_even_split_and_one_on_all_one_side():
    assert bias_score(5, 5) == 0.0
    assert bias_score(9, 0) == 1.0
    assert bias_score(0, 0) is None


def test_bias_score_matches_reputation_definition():
    """abs(left/total − 0.5) · 2 — a 75/25 split scores 0.5."""
    assert bias_score(3, 1) == pytest.approx(0.5)


# --- token (JSON-safe histogram key) ----------------------------------------


def test_token_scalars_and_collections():
    assert token("cat") == "cat"
    assert token(3) == "3"
    assert token(True) == "true"
    # Lists are order-preserving; equal answers collapse to the same key.
    assert token(["b", "a"]) == token(["b", "a"])
    assert token(["a", "b"]) != token(["b", "a"])


# --- throughput / ETA -------------------------------------------------------


def test_throughput_rate_and_eta():
    """4 labels within the last 2h window, 10 slots remaining.

    rate = 4 / 2 = 2 labels/hr; ETA = 10 / 2 = 5h.
    """
    now = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
    stamps = [now - timedelta(minutes=m) for m in (5, 30, 60, 110)]
    r = throughput(stamps, 10, now=now, window_hours=2.0)
    assert r.labels_in_window == 4
    assert r.labels_per_hour == pytest.approx(2.0)
    assert r.eta_hours == pytest.approx(5.0)


def test_throughput_excludes_labels_outside_the_window():
    now = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
    stamps = [now - timedelta(hours=h) for h in (0.5, 1.0, 30.0)]  # last one is old
    r = throughput(stamps, 6, now=now, window_hours=24.0)
    assert r.labels_in_window == 2


def test_throughput_eta_is_none_when_stalled():
    now = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
    r = throughput([], 5, now=now)
    assert r.labels_per_hour == 0.0
    assert r.eta_hours is None


def test_throughput_treats_naive_timestamps_as_utc():
    """Postgres can hand back naive datetimes; the helper must not crash on them."""
    now = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
    naive = datetime(2026, 7, 22, 11, 30)  # 30 min ago, no tzinfo
    r = throughput([naive], 2, now=now, window_hours=1.0)
    assert r.labels_in_window == 1

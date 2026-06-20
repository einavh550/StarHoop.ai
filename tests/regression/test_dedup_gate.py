"""Regression gate for Fix 3 (dedup by player).

Drives the real ``dedup_overlapping_events`` with the synthetic golden scenario
and asserts, via the QA metrics, that the by-player dedup removes the
cross-track duplicate clip WITHOUT dropping distinct players. This is the gate
that must pass before ``dedup_by_player`` is flipped on.
"""

from __future__ import annotations

from app.cv import qa_metrics
from app.cv.highlights.ranking import dedup_overlapping_events, score_event
from tests.regression import fixtures

PAD_PRE = 2.0
PAD_POST = 2.0


def _ranked(events):
    pairs = [(e, score_event(e)) for e in events]
    pairs.sort(key=lambda pair: (-pair[1], pair[0].start_timestamp_sec))
    return pairs


def test_current_behavior_leaves_fragmented_duplicate() -> None:
    events = fixtures.golden_events()
    result = dedup_overlapping_events(_ranked(events), pad_pre_sec=PAD_PRE, pad_post_sec=PAD_POST)
    kept = [e for e, _ in result]
    # Track-keyed dedup cannot collapse player 40's two fragments.
    rate = qa_metrics.duplicate_clip_rate(kept, pad_pre_sec=PAD_PRE, pad_post_sec=PAD_POST)
    assert rate > 0.0


def test_by_player_dedup_eliminates_duplicate_clip_rate() -> None:
    events = fixtures.golden_events()
    result = dedup_overlapping_events(
        _ranked(events), pad_pre_sec=PAD_PRE, pad_post_sec=PAD_POST, by_player=True
    )
    kept = [e for e, _ in result]

    # The fragmented duplicate is gone -> zero duplicate-clip rate.
    rate = qa_metrics.duplicate_clip_rate(kept, pad_pre_sec=PAD_PRE, pad_post_sec=PAD_POST)
    assert rate == 0.0

    # But the two genuinely-distinct players (40 and 41) both survive.
    surviving_players = {e.mapped_player_id for e in kept}
    assert {40, 41} <= surviving_players

"""Correctness tests for the QA metric tooling (the regression harness core).

These lock down the metric functions themselves so later fixes can rely on them
as a trustworthy gate. The metrics are also exercised against the synthetic
golden scenario to confirm they detect the known bugs.
"""

from __future__ import annotations

from app.cv import qa_metrics
from tests.regression import fixtures


PAD_PRE = 2.0
PAD_POST = 2.0


def test_identity_key_prefers_player_then_track() -> None:
    assert qa_metrics.identity_key({"mapped_player_id": 40, "track_id": 5}) == ("player", 40)
    assert qa_metrics.identity_key({"mapped_player_id": None, "track_id": 5}) == ("track", 5)


def test_duplicate_clip_pairs_detects_cross_track_same_player() -> None:
    events = fixtures.golden_events()
    pairs = qa_metrics.duplicate_clip_pairs(events, pad_pre_sec=PAD_PRE, pad_post_sec=PAD_POST)
    # Events 0 and 1 are the same player (40) / same type / overlapping windows.
    assert (0, 1) in pairs
    # Event 2 is a different player at the same time -> not a duplicate.
    assert all(2 not in pair for pair in pairs)


def test_duplicate_clip_rate_counts_redundant_events() -> None:
    events = fixtures.golden_events()
    rate = qa_metrics.duplicate_clip_rate(events, pad_pre_sec=PAD_PRE, pad_post_sec=PAD_POST)
    # 1 redundant event (index 1) out of 4 total.
    assert rate == 0.25


def test_duplicate_clip_rate_zero_when_no_overlap() -> None:
    events = fixtures.golden_events()[2:]  # drop the overlapping pair
    rate = qa_metrics.duplicate_clip_rate(events, pad_pre_sec=PAD_PRE, pad_post_sec=PAD_POST)
    assert rate == 0.0


def test_tracks_per_player_flags_fragmentation() -> None:
    per_player = qa_metrics.tracks_per_player(fixtures.TRACK_TO_PLAYER)
    assert per_player[40] == 2  # tracks 5 and 12
    assert per_player[41] == 1
    assert qa_metrics.max_tracks_per_player(fixtures.TRACK_TO_PLAYER) == 2


def test_duplicate_identity_frame_count_detects_two_boxes_one_player() -> None:
    frames = fixtures.golden_frames()
    count = qa_metrics.duplicate_identity_frame_count(frames, fixtures.TRACK_TO_PLAYER)
    # Every one of the 10 frames carries player 40 on both track 5 and 12.
    assert count == 10


def test_event_type_precision_penalizes_misclassified_block() -> None:
    ground_truth = [
        {"event_type": "jump_shot", "start_timestamp_sec": 30.0, "end_timestamp_sec": 31.0},
    ]
    predicted = [
        {"event_type": "shot_block", "start_timestamp_sec": 30.0, "end_timestamp_sec": 31.0},
    ]
    precision = qa_metrics.event_type_precision(predicted, ground_truth)
    # The block prediction has no matching ground-truth block -> 0 precision.
    assert precision["shot_block"] == 0.0
    assert precision["overall"] == 0.0


def test_event_type_precision_rewards_correct_label() -> None:
    ground_truth = [
        {"event_type": "jump_shot", "start_timestamp_sec": 30.0, "end_timestamp_sec": 31.0},
    ]
    predicted = [
        {"event_type": "jump_shot", "start_timestamp_sec": 30.1, "end_timestamp_sec": 31.1},
    ]
    precision = qa_metrics.event_type_precision(predicted, ground_truth)
    assert precision["jump_shot"] == 1.0
    assert precision["overall"] == 1.0

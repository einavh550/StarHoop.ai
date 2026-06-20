"""Unit tests for the pure helpers behind Fix 2 (action voting / exclusive IoS).

These exercise the deterministic post-processing logic without loading any of
the heavy CV models (RF-DETR / SAM-2 / SigLIP), which are imported lazily inside
``process_video``.
"""

from __future__ import annotations

import numpy as np

from app.cv.pipeline import (
    _assign_actions,
    _box_iou,
    _find_unmatched_detections,
    _majority_action,
    _resolve_overlapping_tracks,
)


def test_assign_actions_non_exclusive_allows_detection_reuse() -> None:
    # rows = SAM-2 tracks, cols = RF-DETR detections.
    ios = np.array([[0.9, 0.6], [0.8, 0.7]])
    pairs = _assign_actions(ios, 0.5, exclusive_detections=False)
    # Each track grabs its best detection; detection 0 is reused by both tracks.
    assert pairs == [(0, 0), (1, 0)]


def test_assign_actions_exclusive_consumes_each_detection_once() -> None:
    ios = np.array([[0.9, 0.6], [0.8, 0.7]])
    pairs = _assign_actions(ios, 0.5, exclusive_detections=True)
    # Track 0 takes detection 0 (0.9); track 1 then takes the remaining det 1.
    assert pairs == [(0, 0), (1, 1)]


def test_assign_actions_respects_threshold() -> None:
    ios = np.array([[0.4, 0.2]])
    assert _assign_actions(ios, 0.5, exclusive_detections=True) == []


def test_majority_action_picks_dominant_class() -> None:
    history = [(1, "player-jump-shot", 0.6), (1, "player-jump-shot", 0.7), (5, "player-shot-block", 0.95)]
    # Class 1 has 2 votes vs 1 -> wins even though the block had higher conf.
    assert _majority_action(history) == (1, "player-jump-shot", 0.7)


def test_majority_action_breaks_ties_on_summed_confidence() -> None:
    history = [(1, "player-jump-shot", 0.5), (5, "player-shot-block", 0.95)]
    # 1 vote each -> tie broken by summed confidence -> block wins.
    assert _majority_action(history) == (5, "player-shot-block", 0.95)


def test_majority_action_single_observation() -> None:
    assert _majority_action([(3, "player", 0.8)]) == (3, "player", 0.8)


def test_box_iou_identical_boxes() -> None:
    box = np.array([0.0, 0.0, 10.0, 10.0])
    assert _box_iou(box, box) == 1.0


def test_box_iou_disjoint_boxes() -> None:
    a = np.array([0.0, 0.0, 10.0, 10.0])
    b = np.array([20.0, 20.0, 30.0, 30.0])
    assert _box_iou(a, b) == 0.0


def test_resolve_overlapping_tracks_drops_smaller_same_team_box() -> None:
    xyxy = np.array(
        [
            [0.0, 0.0, 100.0, 100.0],  # big
            [0.0, 0.0, 90.0, 90.0],    # heavily overlapping, smaller -> dropped
        ]
    )
    keep = _resolve_overlapping_tracks(xyxy, teams=[0, 0], iou_threshold=0.8)
    assert keep == [0]


def test_resolve_overlapping_tracks_keeps_different_teams() -> None:
    xyxy = np.array(
        [
            [0.0, 0.0, 100.0, 100.0],
            [0.0, 0.0, 90.0, 90.0],
        ]
    )
    # Same overlap but different teams (offense vs defense) -> both kept.
    keep = _resolve_overlapping_tracks(xyxy, teams=[0, 1], iou_threshold=0.8)
    assert keep == [0, 1]


def test_resolve_overlapping_tracks_keeps_unknown_team() -> None:
    xyxy = np.array(
        [
            [0.0, 0.0, 100.0, 100.0],
            [0.0, 0.0, 90.0, 90.0],
        ]
    )
    keep = _resolve_overlapping_tracks(xyxy, teams=[None, 0], iou_threshold=0.8)
    assert keep == [0, 1]


def test_resolve_overlapping_tracks_keeps_low_overlap() -> None:
    xyxy = np.array(
        [
            [0.0, 0.0, 100.0, 100.0],
            [80.0, 80.0, 180.0, 180.0],  # small overlap, below threshold
        ]
    )
    keep = _resolve_overlapping_tracks(xyxy, teams=[0, 0], iou_threshold=0.8)
    assert keep == [0, 1]


def test_find_unmatched_detections_flags_new_player() -> None:
    detections = np.array(
        [
            [0.0, 0.0, 50.0, 100.0],      # matches an existing track
            [500.0, 0.0, 550.0, 100.0],   # nobody is tracking here -> unmatched
        ]
    )
    tracks = np.array([[0.0, 0.0, 50.0, 100.0]])
    unmatched = _find_unmatched_detections(detections, tracks, match_iou=0.3)
    assert unmatched == [1]


def test_find_unmatched_detections_all_new_when_no_tracks() -> None:
    detections = np.array([[0.0, 0.0, 50.0, 100.0], [60.0, 0.0, 110.0, 100.0]])
    tracks = np.empty((0, 4), dtype=np.float32)
    unmatched = _find_unmatched_detections(detections, tracks, match_iou=0.3)
    assert unmatched == [0, 1]


def test_find_unmatched_detections_none_when_all_covered() -> None:
    detections = np.array([[0.0, 0.0, 50.0, 100.0]])
    tracks = np.array([[0.0, 0.0, 50.0, 100.0]])
    unmatched = _find_unmatched_detections(detections, tracks, match_iou=0.3)
    assert unmatched == []

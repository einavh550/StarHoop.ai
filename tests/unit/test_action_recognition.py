from app.cv.actions import ActionCandidate, ActionRecognizer, TrackObservation


def test_detect_shot_attempt_positive_case() -> None:
    observations = [
        TrackObservation(frame_number=0, timestamp_sec=0.00, center_y=240.0, detection_confidence=0.90),
        TrackObservation(frame_number=1, timestamp_sec=0.03, center_y=230.0, detection_confidence=0.90),
        TrackObservation(frame_number=2, timestamp_sec=0.06, center_y=220.0, detection_confidence=0.91),
        TrackObservation(frame_number=3, timestamp_sec=0.10, center_y=205.0, detection_confidence=0.91),
        TrackObservation(frame_number=4, timestamp_sec=0.13, center_y=215.0, detection_confidence=0.92),
        TrackObservation(frame_number=5, timestamp_sec=0.16, center_y=228.0, detection_confidence=0.92),
        TrackObservation(frame_number=6, timestamp_sec=0.20, center_y=238.0, detection_confidence=0.93),
    ]

    candidate = ActionRecognizer._detect_shot_attempt_for_segment(
        track_id=11,
        observations=observations,
        mapped_player_id=7,
    )

    assert candidate is not None
    assert candidate.action_type == "shot_attempt"
    assert candidate.track_id == 11
    assert candidate.mapped_player_id == 7
    assert 0.6 <= candidate.action_confidence <= 1.0

    
def test_detect_shot_attempt_negative_case_insufficient_motion() -> None:
    observations = [
        TrackObservation(frame_number=0, timestamp_sec=0.00, center_y=240.0, detection_confidence=0.90),
        TrackObservation(frame_number=1, timestamp_sec=0.03, center_y=238.0, detection_confidence=0.90),
        TrackObservation(frame_number=2, timestamp_sec=0.06, center_y=236.0, detection_confidence=0.90),
        TrackObservation(frame_number=3, timestamp_sec=0.10, center_y=235.0, detection_confidence=0.90),
        TrackObservation(frame_number=4, timestamp_sec=0.13, center_y=236.0, detection_confidence=0.90),
        TrackObservation(frame_number=5, timestamp_sec=0.16, center_y=237.0, detection_confidence=0.90),
    ]

    candidate = ActionRecognizer._detect_shot_attempt_for_segment(
        track_id=12,
        observations=observations,
        mapped_player_id=None,
    )

    assert candidate is None


def test_split_contiguous_segments() -> None:
    observations = [
        TrackObservation(frame_number=1, timestamp_sec=0.03, center_y=100.0, detection_confidence=0.9),
        TrackObservation(frame_number=3, timestamp_sec=0.10, center_y=99.0, detection_confidence=0.9),
        TrackObservation(frame_number=15, timestamp_sec=0.50, center_y=101.0, detection_confidence=0.9),
    ]

    segments = ActionRecognizer._split_contiguous_segments(observations, max_frame_gap=5)
    assert len(segments) == 2
    assert len(segments[0]) == 2
    assert len(segments[1]) == 1


def test_filter_track_candidates_suppresses_overlaps() -> None:
    candidates = [
        ActionCandidate(
            track_id=1,
            action_type="shot_attempt",
            action_confidence=0.95,
            start_frame=100,
            end_frame=130,
            start_timestamp_sec=3.3,
            end_timestamp_sec=4.3,
            mapped_player_id=None,
        ),
        ActionCandidate(
            track_id=1,
            action_type="shot_attempt",
            action_confidence=0.88,
            start_frame=106,
            end_frame=134,
            start_timestamp_sec=3.5,
            end_timestamp_sec=4.5,
            mapped_player_id=None,
        ),
        ActionCandidate(
            track_id=1,
            action_type="shot_attempt",
            action_confidence=0.91,
            start_frame=180,
            end_frame=210,
            start_timestamp_sec=6.0,
            end_timestamp_sec=7.0,
            mapped_player_id=None,
        ),
    ]

    filtered = ActionRecognizer._filter_track_candidates(candidates)

    assert len(filtered) == 2
    confidences = sorted([c.action_confidence for c in filtered], reverse=True)
    assert confidences == [0.95, 0.91]

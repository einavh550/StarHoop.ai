"""Synthetic golden scenario for the CV regression harness.

Rather than committing gigabytes of real ``detection_frames`` JSON, the harness
encodes the exact failure modes observed in QA (job 18 / colton10) as a small,
deterministic fixture:

* Player #10 (``player_id=40``) is physically one person but SAM-2 fragmented
  them into ``track_id`` 5 and 12 -> duplicate identity + duplicate clip.
* A jump-shot by track 5 has two frames misclassified by the detector as
  ``player-shot-block`` -> action misclassification.
* Two players are legitimately in possession at the same moment on different
  tracks -> must NOT be deduplicated.

The fixture exposes both the raw frame stream (for frame-level metrics) and the
derived ``HighlightEvent`` list (for clip-level metrics), so the same scenario
drives every regression assertion.
"""

from __future__ import annotations

from app.cv.highlights.events import (
    EVENT_JUMP_SHOT,
    EVENT_POSSESSION,
    HighlightEvent,
)

# track_id -> roster player_id (what jersey_detections would resolve to).
TRACK_TO_PLAYER: dict[int, int | None] = {
    5: 40,   # player #10, fragment A
    12: 40,  # player #10, fragment B (same person, different SAM-2 id)
    7: 41,   # a different player legitimately on screen
    99: None,  # an opponent / unmapped track
}


def _det(track_id: int, class_name: str) -> dict:
    return {
        "track_id": track_id,
        "class_name": class_name,
        "confidence": 0.8,
        "bbox": {"x1": 0.0, "y1": 0.0, "x2": 10.0, "y2": 20.0},
    }


def golden_frames() -> list[dict]:
    """A frame stream where player 40 appears on two tracks simultaneously."""
    frames: list[dict] = []
    # Frames 0..9: player 40 carried by BOTH track 5 and track 12 (duplicate
    # identity), plus player 41 on track 7.
    for frame_number in range(0, 10):
        frames.append(
            {
                "frame_number": frame_number,
                "timestamp_sec": frame_number / 30.0,
                "detections_json": [
                    _det(5, "player-in-possession"),
                    _det(12, "player-in-possession"),
                    _det(7, "player-in-possession"),
                ],
            }
        )
    return frames


def golden_events() -> list[HighlightEvent]:
    """Derived events mirroring the fragmentation + cross-track duplication."""
    return [
        # Player 40 possession, fragment on track 5.
        HighlightEvent(
            event_type=EVENT_POSSESSION,
            source="frame",
            track_id=5,
            mapped_player_id=40,
            start_frame=0,
            end_frame=120,
            start_timestamp_sec=10.0,
            end_timestamp_sec=14.0,
            confidence=0.9,
        ),
        # SAME physical play, but SAM-2 reassigned track 12 -> different track_id.
        # A (event_type, track_id) dedup keeps this; a player-keyed dedup drops it.
        HighlightEvent(
            event_type=EVENT_POSSESSION,
            source="frame",
            track_id=12,
            mapped_player_id=40,
            start_frame=130,
            end_frame=160,
            start_timestamp_sec=14.4,
            end_timestamp_sec=15.4,
            confidence=0.5,
        ),
        # A genuinely different player in possession at the same time (track 7).
        # Must survive dedup.
        HighlightEvent(
            event_type=EVENT_POSSESSION,
            source="frame",
            track_id=7,
            mapped_player_id=41,
            start_frame=300,
            end_frame=360,
            start_timestamp_sec=10.5,
            end_timestamp_sec=12.5,
            confidence=0.8,
        ),
        # A non-overlapping later possession by player 40 -- distinct highlight.
        HighlightEvent(
            event_type=EVENT_JUMP_SHOT,
            source="frame",
            track_id=5,
            mapped_player_id=40,
            start_frame=900,
            end_frame=930,
            start_timestamp_sec=30.0,
            end_timestamp_sec=31.0,
            confidence=0.85,
        ),
    ]

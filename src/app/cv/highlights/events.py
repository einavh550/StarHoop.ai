"""Derive highlight-worthy events from a completed video job.

Two complementary sources are combined into one timeline of
:class:`HighlightEvent` objects:

* **action** events come from the ``action_detections`` table (currently
  ``shot_attempt``), which already carries a mapped player and a confidence.
* **frame** events are reconstructed by scanning ``detection_frames`` for the
  basketball action classes the detector emits per frame
  (``player-layup-dunk``, ``player-shot-block``, ``player-in-possession``) and
  grouping consecutive observations of the same ``(class, track_id)`` into
  contiguous segments.

Made shots are inferred by correlating ``ball-in-basket`` frame timestamps with
the end of each shot/layup event. Player identity for frame events is resolved
from the per-track jersey mapping in ``jersey_detections``.

``derive_events`` deliberately returns *every* player's events (a single source
of truth). The optional per-player filter for Milestone 5's minimal player reel
is applied downstream in the service, not here.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import ActionDetection, DetectionFrame, JerseyDetection, VideoJob

# Event-type identifiers used throughout the highlight pipeline.
EVENT_SHOT_ATTEMPT = "shot_attempt"
EVENT_LAYUP_DUNK = "layup_dunk"
EVENT_JUMP_SHOT = "jump_shot"
EVENT_SHOT_BLOCK = "shot_block"
EVENT_POSSESSION = "possession"
EVENT_BALL_IN_BASKET = "ball_in_basket"

ALL_EVENT_TYPES: tuple[str, ...] = (
    EVENT_SHOT_ATTEMPT,
    EVENT_LAYUP_DUNK,
    EVENT_JUMP_SHOT,
    EVENT_SHOT_BLOCK,
    EVENT_POSSESSION,
    EVENT_BALL_IN_BASKET,
)

# Frame detector class names -> highlight event types.
FRAME_EVENT_CLASS_MAP: dict[str, str] = {
    "player-layup-dunk": EVENT_LAYUP_DUNK,
    "player-jump-shot": EVENT_JUMP_SHOT,
    "player-shot-block": EVENT_SHOT_BLOCK,
    "player-in-possession": EVENT_POSSESSION,
}

BALL_IN_BASKET_CLASS = "ball-in-basket"

# Event types eligible to be flagged as a made shot via ball-in-basket proximity.
MADE_ELIGIBLE_EVENT_TYPES: frozenset[str] = frozenset(
    {EVENT_SHOT_ATTEMPT, EVENT_LAYUP_DUNK, EVENT_JUMP_SHOT}
)

# High-value action types that are most often produced by 1-2 frame detector
# blips (a blocker's box momentarily matching the shooter's mask, etc.). When
# Fix 2 gating is enabled these require stronger evidence before becoming an
# event, so a phantom block/jump-shot cannot reach the reel.
HIGH_VALUE_EVENT_TYPES: frozenset[str] = frozenset({EVENT_SHOT_BLOCK, EVENT_JUMP_SHOT})


@dataclass
class FrameObservation:
    frame_number: int
    timestamp_sec: float
    confidence: float


@dataclass
class HighlightEvent:
    event_type: str
    source: str  # "action" | "frame"
    track_id: int | None
    mapped_player_id: int | None
    start_frame: int
    end_frame: int
    start_timestamp_sec: float
    end_timestamp_sec: float
    confidence: float
    made: bool | None = None


def derive_events(
    db: Session,
    video_job_id: int,
    *,
    max_gap_sec: float = 0.6,
    min_frame_event_observations: int = 2,
    made_shot_window_sec: float = 1.5,
    high_value_gating: bool = False,
    high_value_min_observations: int = 4,
    high_value_min_confidence: float = 0.5,
) -> list[HighlightEvent]:
    """Build the full list of highlight events for ``video_job_id``.

    Args:
        db: Active database session.
        video_job_id: Target job. Must be ``completed``.
        max_gap_sec: Maximum time gap between consecutive observations of the
            same ``(class, track_id)`` before they are split into two events.
        min_frame_event_observations: Minimum observations required to accept a
            frame-derived segment (suppresses single-frame noise, e.g. fleeting
            possession blips).
        made_shot_window_sec: A shot/layup is marked ``made`` if a
            ``ball-in-basket`` detection appears within this window after the
            event ends.
        high_value_gating: When set (Fix 2), high-value events
            (:data:`HIGH_VALUE_EVENT_TYPES`) must clear stronger thresholds so a
            brief detector blip cannot manufacture a block/jump-shot.
        high_value_min_observations: Minimum observations for a high-value event
            when gating is on.
        high_value_min_confidence: Minimum mean confidence for a high-value event
            when gating is on.

    Returns:
        Events sorted by start timestamp.

    Raises:
        ValueError: If the job does not exist or is not completed.
    """
    job = db.query(VideoJob).filter(VideoJob.id == video_job_id).first()
    if job is None:
        raise ValueError(f"VideoJob {video_job_id} not found")
    if job.status != "completed":
        raise ValueError(f"VideoJob {video_job_id} must be completed before deriving highlight events")

    frames = (
        db.query(DetectionFrame)
        .filter(DetectionFrame.video_job_id == video_job_id)
        .order_by(DetectionFrame.frame_number.asc())
        .all()
    )

    player_by_track = {
        det.track_id: det.mapped_player_id
        for det in db.query(JerseyDetection)
        .filter(JerseyDetection.video_job_id == video_job_id)
        .all()
    }

    action_events = _derive_action_events(db, video_job_id)
    frame_events = _derive_frame_events(
        frames,
        player_by_track=player_by_track,
        max_gap_sec=max_gap_sec,
        min_observations=min_frame_event_observations,
        high_value_gating=high_value_gating,
        high_value_min_observations=high_value_min_observations,
        high_value_min_confidence=high_value_min_confidence,
    )
    basket_events = _derive_ball_in_basket_events(frames, max_gap_sec=max_gap_sec)

    events = action_events + frame_events + basket_events
    _apply_made_shot_flags(events, frames, made_shot_window_sec=made_shot_window_sec)

    events.sort(key=lambda e: (e.start_timestamp_sec, e.start_frame))
    return events


def _derive_action_events(db: Session, video_job_id: int) -> list[HighlightEvent]:
    rows = (
        db.query(ActionDetection)
        .filter(ActionDetection.video_job_id == video_job_id)
        .order_by(ActionDetection.start_frame.asc())
        .all()
    )
    events: list[HighlightEvent] = []
    for row in rows:
        events.append(
            HighlightEvent(
                event_type=row.action_type,
                source="action",
                track_id=row.track_id,
                mapped_player_id=row.mapped_player_id,
                start_frame=int(row.start_frame),
                end_frame=int(row.end_frame),
                start_timestamp_sec=float(row.start_timestamp_sec),
                end_timestamp_sec=float(row.end_timestamp_sec),
                confidence=float(row.action_confidence),
            )
        )
    return events


def _derive_frame_events(
    frames,
    *,
    player_by_track: dict[int, int | None],
    max_gap_sec: float,
    min_observations: int,
    high_value_gating: bool = False,
    high_value_min_observations: int = 4,
    high_value_min_confidence: float = 0.5,
) -> list[HighlightEvent]:
    # Group observations by (event_type, track_id).
    observations: dict[tuple[str, int], list[FrameObservation]] = defaultdict(list)
    for frame in frames:
        frame_number = int(frame.frame_number)
        timestamp = float(frame.timestamp_sec)
        for det in frame.detections_json or []:
            class_name = (det.get("class_name") or "").lower()
            event_type = FRAME_EVENT_CLASS_MAP.get(class_name)
            if event_type is None:
                continue
            track_id = det.get("track_id")
            if track_id is None:
                continue
            observations[(event_type, int(track_id))].append(
                FrameObservation(
                    frame_number=frame_number,
                    timestamp_sec=timestamp,
                    confidence=float(det.get("confidence") or 0.0),
                )
            )

    events: list[HighlightEvent] = []
    for (event_type, track_id), obs in observations.items():
        is_high_value = high_value_gating and event_type in HIGH_VALUE_EVENT_TYPES
        required_observations = (
            max(min_observations, high_value_min_observations)
            if is_high_value
            else min_observations
        )
        for segment in _split_segments(obs, max_gap_sec=max_gap_sec):
            if len(segment) < required_observations:
                continue
            start = segment[0]
            end = segment[-1]
            confidences = [o.confidence for o in segment]
            mean_confidence = sum(confidences) / len(confidences)
            # Gate high-value events on confidence so a low-confidence blip that
            # happens to persist for a few frames still cannot become a block.
            if is_high_value and mean_confidence < high_value_min_confidence:
                continue
            events.append(
                HighlightEvent(
                    event_type=event_type,
                    source="frame",
                    track_id=track_id,
                    mapped_player_id=player_by_track.get(track_id),
                    start_frame=start.frame_number,
                    end_frame=end.frame_number,
                    start_timestamp_sec=start.timestamp_sec,
                    end_timestamp_sec=end.timestamp_sec,
                    confidence=round(mean_confidence, 3),
                )
            )
    return events


def _derive_ball_in_basket_events(
    frames,
    *,
    max_gap_sec: float,
) -> list[HighlightEvent]:
    # ``ball-in-basket`` is detected on the ball, not a tracked player, so these
    # events carry no track/player. Consecutive detections of the same made
    # basket are grouped into one event to avoid double-counting.
    observations: list[FrameObservation] = []
    for frame in frames:
        frame_number = int(frame.frame_number)
        timestamp = float(frame.timestamp_sec)
        for det in frame.detections_json or []:
            if (det.get("class_name") or "").lower() != BALL_IN_BASKET_CLASS:
                continue
            observations.append(
                FrameObservation(
                    frame_number=frame_number,
                    timestamp_sec=timestamp,
                    confidence=float(det.get("confidence") or 0.0),
                )
            )

    events: list[HighlightEvent] = []
    for segment in _split_segments(observations, max_gap_sec=max_gap_sec):
        start = segment[0]
        end = segment[-1]
        confidences = [o.confidence for o in segment]
        events.append(
            HighlightEvent(
                event_type=EVENT_BALL_IN_BASKET,
                source="frame",
                track_id=None,
                mapped_player_id=None,
                start_frame=start.frame_number,
                end_frame=end.frame_number,
                start_timestamp_sec=start.timestamp_sec,
                end_timestamp_sec=end.timestamp_sec,
                confidence=round(sum(confidences) / len(confidences), 3),
            )
        )
    return events


def _split_segments(
    observations: list[FrameObservation],
    *,
    max_gap_sec: float,
) -> list[list[FrameObservation]]:
    if not observations:
        return []

    ordered = sorted(observations, key=lambda o: o.frame_number)
    segments: list[list[FrameObservation]] = [[ordered[0]]]
    for obs in ordered[1:]:
        prev = segments[-1][-1]
        if obs.timestamp_sec - prev.timestamp_sec <= max_gap_sec:
            segments[-1].append(obs)
        else:
            segments.append([obs])
    return segments


def _apply_made_shot_flags(
    events: list[HighlightEvent],
    frames,
    *,
    made_shot_window_sec: float,
) -> None:
    basket_timestamps = sorted(
        float(frame.timestamp_sec)
        for frame in frames
        for det in (frame.detections_json or [])
        if (det.get("class_name") or "").lower() == BALL_IN_BASKET_CLASS
    )
    if not basket_timestamps:
        return

    for event in events:
        if event.event_type not in MADE_ELIGIBLE_EVENT_TYPES:
            continue
        event.made = _has_basket_within_window(
            basket_timestamps,
            event.end_timestamp_sec,
            made_shot_window_sec,
        )


def _has_basket_within_window(
    basket_timestamps: list[float],
    event_end_sec: float,
    window_sec: float,
) -> bool:
    # basket_timestamps is sorted; linear scan is fine for typical volumes.
    upper = event_end_sec + window_sec
    for ts in basket_timestamps:
        if ts < event_end_sec:
            continue
        if ts <= upper:
            return True
        break
    return False

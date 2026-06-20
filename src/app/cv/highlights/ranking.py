"""Rank derived highlight events so the best moments lead the reel.

Scoring is a transparent weighted sum: a base weight per event type, a bonus for
confirmed made shots, and a smaller contribution from the detector confidence.
Events are sorted by descending score and capped at ``max_clips``.
"""

from __future__ import annotations

from collections import defaultdict

from app.cv.highlights.events import (
    EVENT_BALL_IN_BASKET,
    EVENT_JUMP_SHOT,
    EVENT_LAYUP_DUNK,
    EVENT_POSSESSION,
    EVENT_SHOT_ATTEMPT,
    EVENT_SHOT_BLOCK,
    HighlightEvent,
)

# Base desirability per event type (dunk > block > shot > possession).
EVENT_TYPE_WEIGHTS: dict[str, float] = {
    EVENT_LAYUP_DUNK: 1.0,
    EVENT_SHOT_BLOCK: 0.9,
    EVENT_BALL_IN_BASKET: 0.85,
    EVENT_JUMP_SHOT: 0.75,
    EVENT_SHOT_ATTEMPT: 0.7,
    EVENT_POSSESSION: 0.4,
}
_DEFAULT_WEIGHT = 0.5

MADE_SHOT_BONUS = 0.5
CONFIDENCE_WEIGHT = 0.3


def score_event(event: HighlightEvent) -> float:
    """Return the ranking score for a single event."""
    base = EVENT_TYPE_WEIGHTS.get(event.event_type, _DEFAULT_WEIGHT)
    made_bonus = MADE_SHOT_BONUS if event.made else 0.0
    confidence_term = CONFIDENCE_WEIGHT * max(0.0, min(1.0, event.confidence))
    return round(base + made_bonus + confidence_term, 4)


def rank_events(
    events: list[HighlightEvent],
    *,
    max_clips: int,
    event_types: set[str] | None = None,
    min_confidence: float = 0.0,
) -> list[tuple[HighlightEvent, float]]:
    """Filter, score and order events for the reel.

    Args:
        events: Candidate events (any order).
        max_clips: Maximum number of clips to keep.
        event_types: If provided, only these event types are kept.
        min_confidence: Drop events below this detector confidence.

    Returns:
        ``(event, score)`` pairs sorted by descending score, then by start time
        for stable, chronological tie-breaking. Length is capped at
        ``max_clips``.
    """
    filtered = [
        event
        for event in events
        if (event_types is None or event.event_type in event_types)
        and event.confidence >= min_confidence
    ]

    scored = [(event, score_event(event)) for event in filtered]
    scored.sort(key=lambda pair: (-pair[1], pair[0].start_timestamp_sec, pair[0].start_frame))
    return scored[: max(0, max_clips)]


def dedup_overlapping_events(
    ranked: list[tuple[HighlightEvent, float]],
    *,
    pad_pre_sec: float,
    pad_post_sec: float,
) -> list[tuple[HighlightEvent, float]]:
    """Remove lower-ranked events whose padded clip windows overlap with a
    higher-ranked event of the same ``(event_type, track_id)``.

    Events from different players or different event types are never suppressed
    even if they share a time window — a layup and a possession by different
    players at the same moment are genuinely distinct highlights.

    The most common cause of intra-track overlap is detector drop-outs: a brief
    gap (>``max_gap_sec``) in the detection stream splits one continuous
    possession into two separate events.  With 2-second pre/post padding both
    clips capture nearly identical footage, which appears as the same moment
    repeated in the reel.

    Args:
        ranked: ``(event, score)`` pairs already sorted by descending score
            (as returned by :func:`rank_events`).
        pad_pre_sec: Pre-roll padding applied during clip extraction.
        pad_post_sec: Post-roll padding applied during clip extraction.

    Returns:
        The deduplicated subset in the same score order.
    """
    accepted: list[tuple[HighlightEvent, float]] = []
    # Accepted padded windows keyed by (event_type, track_id).
    windows: dict[tuple[str, int | None], list[tuple[float, float]]] = defaultdict(list)

    for event, score in ranked:
        win_start = event.start_timestamp_sec - pad_pre_sec
        win_end = event.end_timestamp_sec + pad_post_sec
        key = (event.event_type, event.track_id)

        duplicate = any(
            min(win_end, acc_end) - max(win_start, acc_start) > 0
            for acc_start, acc_end in windows[key]
        )
        if not duplicate:
            accepted.append((event, score))
            windows[key].append((win_start, win_end))

    return accepted

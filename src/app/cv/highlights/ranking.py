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


def _dedup_identity(event: HighlightEvent, *, by_player: bool) -> tuple[str, int | None]:
    """Identity used to group events for deduplication.

    With ``by_player`` we key on the mapped roster player (stable across SAM-2
    track fragmentation) and only fall back to ``track_id`` when the player is
    unknown. With ``by_player`` off the key is the raw ``track_id`` — exactly the
    pre-remediation behavior.
    """
    if by_player and event.mapped_player_id is not None:
        return ("player", event.mapped_player_id)
    return ("track", event.track_id)


def dedup_overlapping_events(
    ranked: list[tuple[HighlightEvent, float]],
    *,
    pad_pre_sec: float,
    pad_post_sec: float,
    by_player: bool = False,
    cross_type_suppression: bool = False,
) -> list[tuple[HighlightEvent, float]]:
    """Remove lower-ranked events whose padded clip windows overlap a
    higher-ranked event of the same identity.

    Identity defaults to ``(event_type, track_id)`` (the original behavior). When
    ``by_player`` is set the identity becomes ``(event_type, mapped_player_id)``
    with a ``track_id`` fallback, so a player that SAM-2 fragmented into multiple
    ``track_id``s no longer produces two near-identical clips of the same play —
    the root cause of the duplicate-clip-in-reel bug.

    Events from different players (or, by default, different event types) are
    never suppressed even if they share a time window — a layup and a possession
    by different players at the same moment are genuinely distinct highlights.

    When ``cross_type_suppression`` is set, overlapping clips of the SAME player
    are additionally collapsed *across* event types, keeping only the
    highest-weighted one (e.g. one play that produced both a ``possession`` and a
    ``shot_block`` event for the same player at the same time).

    The most common cause of intra-identity overlap is detector drop-outs: a
    brief gap in the detection stream splits one continuous play into two events.
    With 2-second pre/post padding both clips capture nearly identical footage,
    which appears as the same moment repeated in the reel.

    Args:
        ranked: ``(event, score)`` pairs already sorted by descending score
            (as returned by :func:`rank_events`).
        pad_pre_sec: Pre-roll padding applied during clip extraction.
        pad_post_sec: Post-roll padding applied during clip extraction.
        by_player: Key dedup on the mapped player instead of the raw track.
        cross_type_suppression: Also collapse overlapping same-player clips
            across event types (requires the by-player identity to be useful).

    Returns:
        The deduplicated subset in the same score order.
    """
    accepted: list[tuple[HighlightEvent, float]] = []
    # Accepted padded windows keyed by (event_type, identity) for intra-type dedup.
    windows: dict[tuple[str, tuple[str, int | None]], list[tuple[float, float]]] = defaultdict(list)
    # Accepted padded windows keyed by identity only, for cross-type suppression.
    identity_windows: dict[tuple[str, int | None], list[tuple[float, float]]] = defaultdict(list)

    for event, score in ranked:
        win_start = event.start_timestamp_sec - pad_pre_sec
        win_end = event.end_timestamp_sec + pad_post_sec
        identity = _dedup_identity(event, by_player=by_player)
        key = (event.event_type, identity)

        duplicate = any(
            min(win_end, acc_end) - max(win_start, acc_start) > 0
            for acc_start, acc_end in windows[key]
        )
        if not duplicate and cross_type_suppression:
            duplicate = any(
                min(win_end, acc_end) - max(win_start, acc_start) > 0
                for acc_start, acc_end in identity_windows[identity]
            )

        if not duplicate:
            accepted.append((event, score))
            windows[key].append((win_start, win_end))
            identity_windows[identity].append((win_start, win_end))

    return accepted

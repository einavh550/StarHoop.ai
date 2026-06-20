"""Quality metrics for the CV pipeline, used by the regression harness.

These are pure, dependency-free functions that quantify the failure modes the
remediation targets, so a change can be proven to improve (and never regress)
each one before its feature flag is flipped:

* ``duplicate_clip_rate`` / ``duplicate_clip_pairs`` -- the "same play shown
  twice" bug. Two clips of the *same identity* and *same event type* whose
  padded time windows overlap are counted as a duplicate.
* ``tracks_per_player`` / ``max_tracks_per_player`` -- track fragmentation: how
  many distinct ``track_id``s collapse onto one roster player.
* ``duplicate_identity_frame_count`` -- the "one player, two boxes" bug: frames
  where a single ``mapped_player_id`` is carried by two or more tracks at once.
* ``event_type_precision`` -- action-label correctness (e.g. shot mislabeled as
  block) measured against a ground-truth list by time overlap.

The functions accept lightweight inputs (objects exposing the documented
attributes, or plain dicts) so they work equally on real ``HighlightEvent`` /
``DetectionFrame`` rows and on synthetic fixtures.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    """Read ``name`` from an attribute or a dict key, with a default."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def identity_key(event: Any) -> tuple[str, Any]:
    """Identity used to decide if two clips are 'the same player'.

    Prefers ``mapped_player_id`` (stable across track fragmentation); falls back
    to ``track_id`` when the player is unknown. Unmapped events therefore only
    deduplicate against their own track, which is the safe conservative choice.
    """
    player_id = _attr(event, "mapped_player_id")
    if player_id is not None:
        return ("player", player_id)
    return ("track", _attr(event, "track_id"))


def padded_window(event: Any, *, pad_pre_sec: float, pad_post_sec: float) -> tuple[float, float]:
    """Return the ``[start, end]`` clip window after applying padding."""
    start = float(_attr(event, "start_timestamp_sec", 0.0)) - pad_pre_sec
    end = float(_attr(event, "end_timestamp_sec", 0.0)) + pad_post_sec
    return (start, end)


def _overlaps(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return min(a[1], b[1]) - max(a[0], b[0]) > 0


def duplicate_clip_pairs(
    events: Iterable[Any],
    *,
    pad_pre_sec: float,
    pad_post_sec: float,
    cross_event_type: bool = False,
) -> list[tuple[int, int]]:
    """Return index pairs ``(i, j)`` (i < j) that are duplicate clips.

    Two events are duplicates when they share the same :func:`identity_key`,
    their padded windows overlap, and (unless ``cross_event_type``) they have the
    same ``event_type``. This catches the track-fragmentation duplicate-clip bug
    that a ``(event_type, track_id)``-keyed dedup misses.
    """
    items = list(events)
    pairs: list[tuple[int, int]] = []
    windows = [padded_window(e, pad_pre_sec=pad_pre_sec, pad_post_sec=pad_post_sec) for e in items]
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if identity_key(items[i]) != identity_key(items[j]):
                continue
            if not cross_event_type and _attr(items[i], "event_type") != _attr(items[j], "event_type"):
                continue
            if _overlaps(windows[i], windows[j]):
                pairs.append((i, j))
    return pairs


def duplicate_clip_rate(
    events: Iterable[Any],
    *,
    pad_pre_sec: float,
    pad_post_sec: float,
    cross_event_type: bool = False,
) -> float:
    """Fraction of events that are redundant duplicates (0.0 == none).

    Counts every event that overlaps an earlier same-identity event, divided by
    the total event count.
    """
    items = list(events)
    if not items:
        return 0.0
    pairs = duplicate_clip_pairs(
        items,
        pad_pre_sec=pad_pre_sec,
        pad_post_sec=pad_post_sec,
        cross_event_type=cross_event_type,
    )
    redundant = {j for _, j in pairs}
    return len(redundant) / len(items)


def tracks_per_player(track_to_player: dict[int, int | None]) -> dict[int, int]:
    """Map ``player_id -> number of distinct tracks`` that resolved to them.

    A value > 1 means track fragmentation (one player split across tracks).
    Unmapped tracks (``None``) are ignored.
    """
    counts: dict[int, set[int]] = defaultdict(set)
    for track_id, player_id in track_to_player.items():
        if player_id is None:
            continue
        counts[player_id].add(track_id)
    return {player_id: len(tracks) for player_id, tracks in counts.items()}


def max_tracks_per_player(track_to_player: dict[int, int | None]) -> int:
    """Largest number of tracks collapsed onto a single player (0 if none)."""
    per_player = tracks_per_player(track_to_player)
    return max(per_player.values(), default=0)


def duplicate_identity_frame_count(
    frames: Iterable[Any],
    track_to_player: dict[int, int | None],
) -> int:
    """Count frames where one player is drawn by two or more tracks at once.

    This is the on-screen "duplicate identity" symptom: within a single frame's
    detections, two distinct ``track_id``s map to the same ``mapped_player_id``.
    """
    duplicate_frames = 0
    for frame in frames:
        detections = _attr(frame, "detections_json") or _attr(frame, "detections") or []
        seen_players: dict[int, int] = defaultdict(int)
        for det in detections:
            track_id = _attr(det, "track_id")
            if track_id is None:
                continue
            player_id = track_to_player.get(int(track_id))
            if player_id is None:
                continue
            seen_players[player_id] += 1
        if any(count >= 2 for count in seen_players.values()):
            duplicate_frames += 1
    return duplicate_frames


def event_type_precision(
    predicted: Iterable[Any],
    ground_truth: Iterable[Any],
    *,
    tolerance_sec: float = 0.5,
) -> dict[str, float]:
    """Per-event-type precision of ``predicted`` against ``ground_truth``.

    A predicted event is correct when a ground-truth event overlaps it in time
    (within ``tolerance_sec`` slack on each side) AND shares its ``event_type``.
    Returns ``{event_type: precision}`` plus an ``"overall"`` key. Event types
    with no predictions are omitted.
    """
    preds = list(predicted)
    truth = list(ground_truth)

    per_type_total: dict[str, int] = defaultdict(int)
    per_type_correct: dict[str, int] = defaultdict(int)

    for pred in preds:
        etype = _attr(pred, "event_type")
        per_type_total[etype] += 1
        p_start = float(_attr(pred, "start_timestamp_sec", 0.0)) - tolerance_sec
        p_end = float(_attr(pred, "end_timestamp_sec", 0.0)) + tolerance_sec
        for gt in truth:
            if _attr(gt, "event_type") != etype:
                continue
            g_start = float(_attr(gt, "start_timestamp_sec", 0.0))
            g_end = float(_attr(gt, "end_timestamp_sec", 0.0))
            if _overlaps((p_start, p_end), (g_start, g_end)):
                per_type_correct[etype] += 1
                break

    result: dict[str, float] = {}
    for etype, total in per_type_total.items():
        result[etype] = per_type_correct[etype] / total if total else 0.0

    total_all = sum(per_type_total.values())
    correct_all = sum(per_type_correct.values())
    result["overall"] = correct_all / total_all if total_all else 0.0
    return result

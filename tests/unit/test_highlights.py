"""Unit tests for the Milestone 5 highlight pipeline (pure logic, no DB/ffmpeg)."""

from dataclasses import dataclass

import pytest

from app.cv.highlights import clips as clips_mod
from app.cv.highlights import ffmpeg as ffmpeg_mod
from app.cv.highlights.clips import ClipExtractionError, _escape_concat_path, extract_clip, resolve_source
from app.cv.highlights.events import (
    EVENT_LAYUP_DUNK,
    EVENT_POSSESSION,
    EVENT_SHOT_ATTEMPT,
    FrameObservation,
    HighlightEvent,
    _apply_made_shot_flags,
    _derive_frame_events,
    _has_basket_within_window,
    _split_segments,
)
from app.cv.highlights.ffmpeg import FFmpegError
from app.cv.highlights.ranking import rank_events, score_event


@dataclass
class FakeFrame:
    frame_number: int
    timestamp_sec: float
    detections_json: list[dict]


def _det(class_name: str, track_id: int | None = None, confidence: float = 0.9) -> dict:
    return {"class_name": class_name, "track_id": track_id, "confidence": confidence}


# --------------------------------------------------------------------------- #
# Event derivation
# --------------------------------------------------------------------------- #
def test_split_segments_breaks_on_time_gap() -> None:
    obs = [
        FrameObservation(frame_number=0, timestamp_sec=0.0, confidence=0.9),
        FrameObservation(frame_number=3, timestamp_sec=0.1, confidence=0.9),
        FrameObservation(frame_number=30, timestamp_sec=1.0, confidence=0.9),
    ]
    segments = _split_segments(obs, max_gap_sec=0.6)
    assert len(segments) == 2
    assert [len(s) for s in segments] == [2, 1]


def test_derive_frame_events_groups_by_class_and_track() -> None:
    frames = [
        FakeFrame(0, 0.0, [_det("player-layup-dunk", track_id=7)]),
        FakeFrame(3, 0.1, [_det("player-layup-dunk", track_id=7)]),
        FakeFrame(6, 0.2, [_det("player-in-possession", track_id=9)]),
        FakeFrame(9, 0.3, [_det("player-in-possession", track_id=9)]),
        FakeFrame(12, 0.4, [_det("referee", track_id=1)]),  # ignored class
    ]
    events = _derive_frame_events(
        frames,
        player_by_track={7: 70, 9: None},
        max_gap_sec=0.6,
        min_observations=2,
    )
    by_type = {e.event_type: e for e in events}
    assert set(by_type) == {EVENT_LAYUP_DUNK, EVENT_POSSESSION}
    assert by_type[EVENT_LAYUP_DUNK].track_id == 7
    assert by_type[EVENT_LAYUP_DUNK].mapped_player_id == 70
    assert by_type[EVENT_LAYUP_DUNK].source == "frame"
    assert by_type[EVENT_POSSESSION].mapped_player_id is None


def test_derive_frame_events_drops_short_segments() -> None:
    frames = [FakeFrame(0, 0.0, [_det("player-in-possession", track_id=9)])]
    events = _derive_frame_events(frames, player_by_track={}, max_gap_sec=0.6, min_observations=2)
    assert events == []


def test_has_basket_within_window() -> None:
    baskets = [1.0, 5.0, 5.4]
    assert _has_basket_within_window(baskets, event_end_sec=5.0, window_sec=1.5) is True
    assert _has_basket_within_window(baskets, event_end_sec=2.0, window_sec=1.5) is False
    # Basket before the event end does not count.
    assert _has_basket_within_window([4.9], event_end_sec=5.0, window_sec=1.5) is False


def test_apply_made_shot_flags_only_marks_eligible_events() -> None:
    frames = [FakeFrame(60, 2.6, [_det("ball-in-basket")])]
    shot = HighlightEvent(
        event_type=EVENT_SHOT_ATTEMPT, source="action", track_id=1, mapped_player_id=None,
        start_frame=40, end_frame=50, start_timestamp_sec=1.5, end_timestamp_sec=2.0, confidence=0.8,
    )
    possession = HighlightEvent(
        event_type=EVENT_POSSESSION, source="frame", track_id=2, mapped_player_id=None,
        start_frame=40, end_frame=50, start_timestamp_sec=1.5, end_timestamp_sec=2.0, confidence=0.8,
    )
    _apply_made_shot_flags([shot, possession], frames, made_shot_window_sec=1.5)
    assert shot.made is True
    assert possession.made is None  # possession is never made-eligible


# --------------------------------------------------------------------------- #
# Ranking
# --------------------------------------------------------------------------- #
def _event(event_type: str, confidence: float = 0.5, made: bool | None = None) -> HighlightEvent:
    return HighlightEvent(
        event_type=event_type, source="frame", track_id=1, mapped_player_id=None,
        start_frame=0, end_frame=10, start_timestamp_sec=0.0, end_timestamp_sec=1.0,
        confidence=confidence, made=made,
    )


def test_score_event_made_shot_outranks_miss() -> None:
    made = _event(EVENT_SHOT_ATTEMPT, confidence=0.5, made=True)
    miss = _event(EVENT_SHOT_ATTEMPT, confidence=0.5, made=False)
    assert score_event(made) > score_event(miss)


def test_rank_events_filters_and_caps() -> None:
    events = [
        _event(EVENT_LAYUP_DUNK, confidence=0.9),
        _event(EVENT_POSSESSION, confidence=0.2),
        _event(EVENT_SHOT_ATTEMPT, confidence=0.95),
    ]
    ranked = rank_events(events, max_clips=2, event_types={EVENT_LAYUP_DUNK, EVENT_SHOT_ATTEMPT}, min_confidence=0.0)
    assert len(ranked) == 2
    # layup_dunk (base 1.0) should outrank shot_attempt (base 0.7).
    assert ranked[0][0].event_type == EVENT_LAYUP_DUNK


def test_rank_events_min_confidence_drops_low() -> None:
    events = [_event(EVENT_SHOT_ATTEMPT, confidence=0.1)]
    assert rank_events(events, max_clips=10, min_confidence=0.5) == []


# --------------------------------------------------------------------------- #
# ffmpeg wrapper
# --------------------------------------------------------------------------- #
def test_ensure_ffmpeg_available_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ffmpeg_mod.shutil, "which", lambda _binary: None)
    with pytest.raises(FFmpegError):
        ffmpeg_mod.ensure_ffmpeg_available()


def test_run_ffmpeg_raises_on_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ffmpeg_mod.shutil, "which", lambda _binary: "/usr/bin/" + _binary)

    class _Result:
        returncode = 1
        stderr = "boom"
        stdout = ""

    monkeypatch.setattr(ffmpeg_mod.subprocess, "run", lambda *a, **k: _Result())
    with pytest.raises(FFmpegError, match="boom"):
        ffmpeg_mod.run_ffmpeg(["-i", "x.mp4", "out.mp4"])


# --------------------------------------------------------------------------- #
# clips
# --------------------------------------------------------------------------- #
def test_resolve_source_rejects_unknown_mode() -> None:
    with pytest.raises(ClipExtractionError):
        resolve_source(db=None, job=None, source_mode="bogus")  # type: ignore[arg-type]


def test_resolve_source_clean_missing_file() -> None:
    class _Job:
        id = 1
        storage_path = "/no/such/file.mp4"

    with pytest.raises(ClipExtractionError):
        resolve_source(db=None, job=_Job(), source_mode="clean")  # type: ignore[arg-type]


def test_extract_clip_empty_window_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # Window fully outside the (clamped) source -> empty -> error before ffmpeg runs.
    called = {"ran": False}
    monkeypatch.setattr(clips_mod, "run_ffmpeg", lambda *a, **k: called.__setitem__("ran", True))
    with pytest.raises(ClipExtractionError):
        extract_clip(
            "src.mp4",
            start_sec=100.0,
            end_sec=101.0,
            pad_pre_sec=0.0,
            pad_post_sec=0.0,
            output_path="out.mp4",
            source_duration_sec=10.0,
        )
    assert called["ran"] is False


def test_extract_clip_builds_clamped_window(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    captured: dict[str, list[str]] = {}
    monkeypatch.setattr(clips_mod, "run_ffmpeg", lambda args, **k: captured.__setitem__("args", args))
    duration = extract_clip(
        "src.mp4",
        start_sec=5.0,
        end_sec=6.0,
        pad_pre_sec=2.0,
        pad_post_sec=2.0,
        output_path=tmp_path / "out.mp4",
        source_duration_sec=7.0,
    )
    # start padded to 3.0; end padded to 8.0 but clamped to 7.0 -> duration 4.0.
    assert duration == pytest.approx(4.0)
    args = captured["args"]
    assert "3.000" in args
    assert "4.000" in args


def test_escape_concat_path_escapes_quotes() -> None:
    escaped = _escape_concat_path_helper()
    assert "'\\''" in escaped


def _escape_concat_path_helper() -> str:
    from pathlib import Path

    return _escape_concat_path(Path("/tmp/it's a clip.mp4"))

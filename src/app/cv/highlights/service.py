"""Orchestrate end-to-end highlight reel generation.

Validates the job, derives and ranks events (optionally filtered to a single
player for the minimal per-player reel), extracts a padded clip per selected
event, stitches them into one reel MP4, and persists the reel plus its clips.

The reel row is created in ``processing`` state up front for traceability and
flipped to ``completed`` / ``failed`` as a terminal state, so a crash never
leaves a silently missing record. Each call creates a new reel (history is
preserved).
"""

from __future__ import annotations

import logging
import shutil
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.cv.annotated_export import render_annotated_export
from app.cv.highlights.clips import (
    ClipExtractionError,
    SOURCE_ANNOTATED,
    SOURCE_CLEAN,
    extract_clip,
    resolve_source,
    stitch_clips,
)
from app.cv.highlights.events import ALL_EVENT_TYPES, HighlightEvent, derive_events
from app.cv.highlights.ffmpeg import probe_duration
from app.cv.highlights.ranking import dedup_overlapping_events, rank_events
from app.cv.storage import ensure_storage_directory
from app.db.models import HighlightClip, HighlightReel, Player, VideoJob

logger = logging.getLogger(__name__)


class HighlightGenerationError(RuntimeError):
    """Base error for highlight reel generation failures."""


class PlayerNotFoundError(HighlightGenerationError):
    """The requested player does not exist on the job's team."""


class EmptyReelError(HighlightGenerationError):
    """No events qualified, so there is nothing to stitch into a reel."""


def generate_highlights(
    db: Session,
    video_job_id: int,
    *,
    source_mode: str = SOURCE_CLEAN,
    player_id: int | None = None,
    event_types: set[str] | None = None,
    max_clips: int | None = None,
    min_confidence: float = 0.0,
    pad_pre_sec: float | None = None,
    pad_post_sec: float | None = None,
    made_shot_window_sec: float | None = None,
) -> HighlightReel:
    """Generate and persist a highlight reel for ``video_job_id``.

    When ``player_id`` is ``None`` the result is the master reel (all events for
    all players). When set, the reel is filtered to that player's events only
    (scope ``player``) -- the raw per-player cut; graphics/music are Milestone 6.

    Raises:
        ValueError: Job missing or not completed.
        PlayerNotFoundError: ``player_id`` not on the job's team.
        EmptyReelError: No qualifying events to build a reel from.
        ClipExtractionError / FFmpegError: Media processing failed.
    """
    job = db.query(VideoJob).filter(VideoJob.id == video_job_id).first()
    if job is None:
        raise ValueError(f"VideoJob {video_job_id} not found")
    if job.status != "completed":
        raise ValueError(f"VideoJob {video_job_id} must be completed before generating highlights")

    if player_id is not None:
        player = (
            db.query(Player)
            .filter(Player.id == player_id, Player.team_id == job.team_id)
            .first()
        )
        if player is None:
            raise PlayerNotFoundError(
                f"Player {player_id} not found on team {job.team_id} for job {video_job_id}"
            )

    pad_pre = settings.highlight_pad_pre_sec if pad_pre_sec is None else pad_pre_sec
    pad_post = settings.highlight_pad_post_sec if pad_post_sec is None else pad_post_sec
    clip_cap = settings.highlight_max_clips if max_clips is None else max_clips
    made_window = (
        settings.highlight_made_shot_window_sec if made_shot_window_sec is None else made_shot_window_sec
    )
    selected_event_types = set(event_types) if event_types else set(ALL_EVENT_TYPES)

    events = derive_events(
        db,
        video_job_id,
        made_shot_window_sec=made_window,
        high_value_gating=settings.action_temporal_voting,
        high_value_min_observations=settings.action_high_value_min_observations,
        high_value_min_confidence=settings.action_high_value_min_confidence,
    )

    scope = "all"
    if player_id is not None:
        scope = "player"
        events = [event for event in events if event.mapped_player_id == player_id]
        if not events:
            raise EmptyReelError(
                f"No highlight events mapped to player {player_id} in job {video_job_id}"
            )

    ranked = rank_events(
        events,
        max_clips=clip_cap,
        event_types=selected_event_types,
        min_confidence=min_confidence,
    )
    if not ranked:
        raise EmptyReelError(f"No highlight events qualified for job {video_job_id}")

    ranked = dedup_overlapping_events(
        ranked,
        pad_pre_sec=pad_pre,
        pad_post_sec=pad_post,
        by_player=settings.dedup_by_player,
        cross_type_suppression=settings.dedup_cross_type_suppression,
    )

    reel = HighlightReel(
        video_job_id=video_job_id,
        status="processing",
        source_mode=source_mode,
        scope=scope,
        player_id=player_id,
        clip_count=0,
        total_duration_sec=Decimal("0.000"),
    )
    db.add(reel)
    db.commit()
    db.refresh(reel)

    reel_dir = Path(ensure_storage_directory(settings.highlight_export_dir)) / f"job_{video_job_id}" / f"reel_{reel.id}"
    clips_dir = reel_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    try:
        if source_mode == SOURCE_ANNOTATED and player_id is not None:
            # For per-player annotated reels, annotate ONLY the selected player.
            source_path = render_annotated_export(
                db,
                video_job_id,
                annotated_player_id=player_id,
            ).output_path
        else:
            source_path = resolve_source(db, job, source_mode)
        source_duration = probe_duration(source_path)

        total_duration = 0.0
        clip_paths: list[Path] = []
        for order_index, (event, score) in enumerate(ranked):
            clip_filename = f"clip_{order_index:03d}_{event.event_type}.mp4"
            clip_path = clips_dir / clip_filename
            clip_duration = extract_clip(
                source_path,
                start_sec=event.start_timestamp_sec,
                end_sec=event.end_timestamp_sec,
                pad_pre_sec=pad_pre,
                pad_post_sec=pad_post,
                output_path=clip_path,
                source_duration_sec=source_duration,
            )
            total_duration += clip_duration
            clip_paths.append(clip_path)
            db.add(_build_clip_row(reel.id, video_job_id, order_index, event, score, clip_path, clip_filename))

        output_filename = f"reel_{reel.id}_{scope}.mp4"
        output_path = reel_dir / output_filename
        stitch_clips(clip_paths, output_path)

        reel.status = "completed"
        reel.clip_count = len(clip_paths)
        reel.total_duration_sec = Decimal(f"{total_duration:.3f}")
        reel.output_path = str(output_path.resolve())
        reel.output_filename = output_filename
        db.commit()
        db.refresh(reel)
        logger.info(
            "highlight_reel_created job_id=%s reel_id=%s scope=%s clips=%s",
            video_job_id,
            reel.id,
            scope,
            len(clip_paths),
        )
        return reel
    except Exception as exc:
        db.rollback()
        _mark_reel_failed(db, reel.id, exc)
        shutil.rmtree(reel_dir, ignore_errors=True)
        raise


def _build_clip_row(
    reel_id: int,
    video_job_id: int,
    order_index: int,
    event: HighlightEvent,
    score: float,
    clip_path: Path,
    clip_filename: str,
) -> HighlightClip:
    return HighlightClip(
        reel_id=reel_id,
        video_job_id=video_job_id,
        event_type=event.event_type,
        source=event.source,
        track_id=event.track_id,
        mapped_player_id=event.mapped_player_id,
        start_frame=event.start_frame,
        end_frame=event.end_frame,
        start_timestamp_sec=Decimal(f"{event.start_timestamp_sec:.3f}"),
        end_timestamp_sec=Decimal(f"{event.end_timestamp_sec:.3f}"),
        made=event.made,
        score=score,
        confidence=max(0.0, min(1.0, event.confidence)),
        clip_path=str(clip_path.resolve()),
        clip_filename=clip_filename,
        order_index=order_index,
    )


def _mark_reel_failed(db: Session, reel_id: int, exc: Exception) -> None:
    """Best-effort: flip the reel to ``failed`` with a short error message."""
    try:
        reel = db.query(HighlightReel).filter(HighlightReel.id == reel_id).first()
        if reel is not None:
            reel.status = "failed"
            reel.error_message = str(exc)[:1024]
            db.commit()
    except Exception:
        db.rollback()
        logger.exception("failed to mark highlight reel %s as failed", reel_id)

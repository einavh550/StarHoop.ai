"""Highlight reel endpoints (Milestone 5).

* ``POST /api/videos/{job_id}/highlights/extract`` derives events, extracts and
  stitches clips, and returns the created reel. Omit ``player_id`` for the master
  reel (all players); supply it for a minimal per-player cut.
* ``GET .../highlights/{reel_id}`` returns reel status + clip metadata.
* ``GET .../highlights/{reel_id}/download`` streams the stitched reel MP4.
* ``GET .../highlights/{reel_id}/clips/{clip_id}/download`` streams one clip.
"""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.cv.highlights.clips import ClipExtractionError, VALID_SOURCE_MODES
from app.cv.highlights.events import ALL_EVENT_TYPES
from app.cv.highlights.ffmpeg import FFmpegError
from app.cv.highlights.audio import MusicUnavailableError
from app.cv.highlights.compose import CompositionError
from app.cv.highlights.compose_service import (
    CompositionRequestError,
    ReelNotReadyError,
    compose_reel,
)
from app.cv.highlights.service import (
    EmptyReelError,
    PlayerNotFoundError,
    generate_highlights,
)
from app.cv.schemas import (
    ComposedReelResponse,
    ComposedReelStatusResponse,
    HighlightClipResponse,
    HighlightReelResponse,
    HighlightReelStatusResponse,
)
from app.db.models import ComposedReel, HighlightClip, HighlightReel, VideoJob
from app.db.session import get_db

router = APIRouter(prefix="/api/videos", tags=["highlights"])


def _reel_download_url(job_id: int, reel_id: int) -> str:
    return f"/api/videos/{job_id}/highlights/{reel_id}/download"


def _clip_download_url(job_id: int, reel_id: int, clip_id: int) -> str:
    return f"/api/videos/{job_id}/highlights/{reel_id}/clips/{clip_id}/download"


def _clip_to_response(job_id: int, clip: HighlightClip) -> HighlightClipResponse:
    return HighlightClipResponse(
        clip_id=clip.id,
        order_index=clip.order_index,
        event_type=clip.event_type,
        source=clip.source,
        track_id=clip.track_id,
        mapped_player_id=clip.mapped_player_id,
        start_frame=clip.start_frame,
        end_frame=clip.end_frame,
        start_timestamp_sec=float(clip.start_timestamp_sec),
        end_timestamp_sec=float(clip.end_timestamp_sec),
        made=clip.made,
        score=clip.score,
        confidence=clip.confidence,
        clip_filename=clip.clip_filename,
        download_url=_clip_download_url(job_id, clip.reel_id, clip.id) if clip.clip_filename else None,
    )


def _reel_to_response(team_id: int, reel: HighlightReel) -> HighlightReelResponse:
    return HighlightReelResponse(
        reel_id=reel.id,
        job_id=reel.video_job_id,
        team_id=team_id,
        status=reel.status,
        scope=reel.scope,
        source_mode=reel.source_mode,
        player_id=reel.player_id,
        clip_count=reel.clip_count,
        total_duration_sec=float(reel.total_duration_sec),
        output_filename=reel.output_filename,
        download_url=_reel_download_url(reel.video_job_id, reel.id) if reel.output_filename else None,
        created_at=reel.created_at,
        clips=[_clip_to_response(reel.video_job_id, clip) for clip in reel.clips],
    )


@router.post(
    "/{job_id}/highlights/extract",
    response_model=HighlightReelResponse,
    status_code=status.HTTP_201_CREATED,
)
def extract_highlights(
    job_id: int,
    source: Annotated[str, Query()] = "annotated",
    player_id: Annotated[int | None, Query()] = None,
    max_clips: Annotated[int | None, Query(ge=1, le=200)] = None,
    min_confidence: Annotated[float, Query(ge=0.0, le=1.0)] = 0.0,
    event_types: Annotated[list[str] | None, Query()] = None,
    pad_pre_sec: Annotated[float | None, Query(ge=0.0, le=10.0)] = None,
    pad_post_sec: Annotated[float | None, Query(ge=0.0, le=10.0)] = None,
    db: Session = Depends(get_db),
) -> HighlightReelResponse:
    job = db.query(VideoJob).filter(VideoJob.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"VideoJob {job_id} not found")

    if source not in VALID_SOURCE_MODES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid source '{source}'. Expected one of: {sorted(VALID_SOURCE_MODES)}",
        )

    requested_types: set[str] | None = None
    if event_types:
        unknown = [t for t in event_types if t not in ALL_EVENT_TYPES]
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown event_types {unknown}. Allowed: {list(ALL_EVENT_TYPES)}",
            )
        requested_types = set(event_types)

    try:
        reel = generate_highlights(
            db=db,
            video_job_id=job_id,
            source_mode=source,
            player_id=player_id,
            event_types=requested_types,
            max_clips=max_clips,
            min_confidence=min_confidence,
            pad_pre_sec=pad_pre_sec,
            pad_post_sec=pad_post_sec,
        )
        return _reel_to_response(job.team_id, reel)
    except PlayerNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except EmptyReelError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except (ValueError, ClipExtractionError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FFmpegError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Highlight rendering failed: {exc}",
        ) from exc


def _load_reel(db: Session, job_id: int, reel_id: int) -> tuple[VideoJob, HighlightReel]:
    job = db.query(VideoJob).filter(VideoJob.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"VideoJob {job_id} not found")
    reel = (
        db.query(HighlightReel)
        .filter(HighlightReel.id == reel_id, HighlightReel.video_job_id == job_id)
        .first()
    )
    if reel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Highlight reel {reel_id} not found for job {job_id}",
        )
    return job, reel


@router.get("/{job_id}/highlights/{reel_id}", response_model=HighlightReelStatusResponse)
def get_highlight_reel(job_id: int, reel_id: int, db: Session = Depends(get_db)) -> HighlightReelStatusResponse:
    job, reel = _load_reel(db, job_id, reel_id)

    file_size_bytes: int | None = None
    if reel.output_path:
        output_path = Path(reel.output_path)
        if output_path.exists():
            file_size_bytes = output_path.stat().st_size

    base = _reel_to_response(job.team_id, reel)
    return HighlightReelStatusResponse(
        **base.model_dump(),
        file_size_bytes=file_size_bytes,
        error_message=reel.error_message,
    )


@router.get("/{job_id}/highlights/{reel_id}/download")
def download_highlight_reel(job_id: int, reel_id: int, db: Session = Depends(get_db)):
    _, reel = _load_reel(db, job_id, reel_id)
    if not reel.output_path:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Highlight reel {reel_id} is not ready (status={reel.status})",
        )
    output_path = Path(reel.output_path)
    if not output_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Highlight reel file not found")
    return FileResponse(
        path=str(output_path),
        media_type="video/mp4",
        filename=reel.output_filename or output_path.name,
    )


@router.get("/{job_id}/highlights/{reel_id}/clips/{clip_id}/download")
def download_highlight_clip(job_id: int, reel_id: int, clip_id: int, db: Session = Depends(get_db)):
    _load_reel(db, job_id, reel_id)
    clip = (
        db.query(HighlightClip)
        .filter(HighlightClip.id == clip_id, HighlightClip.reel_id == reel_id)
        .first()
    )
    if clip is None or not clip.clip_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Highlight clip {clip_id} not found for reel {reel_id}",
        )
    clip_path = Path(clip.clip_path)
    if not clip_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Highlight clip file not found")
    return FileResponse(
        path=str(clip_path),
        media_type="video/mp4",
        filename=clip.clip_filename or clip_path.name,
    )


# --------------------------------------------------------------------------- #
# Milestone 6: professional personalized reel composition
# --------------------------------------------------------------------------- #


def _composed_download_url(job_id: int, reel_id: int, composed_id: int) -> str:
    return f"/api/videos/{job_id}/highlights/{reel_id}/compose/{composed_id}/download"


def _composed_to_response(team_id: int, composed: ComposedReel) -> ComposedReelResponse:
    return ComposedReelResponse(
        composed_reel_id=composed.id,
        reel_id=composed.reel_id,
        job_id=composed.video_job_id,
        team_id=team_id,
        player_id=composed.player_id,
        status=composed.status,
        aspect_ratio=composed.aspect_ratio,
        music_track=composed.music_track,
        has_intro=composed.has_intro,
        has_stats=composed.has_stats,
        has_watermark=composed.has_watermark,
        total_duration_sec=float(composed.total_duration_sec),
        output_filename=composed.output_filename,
        download_url=(
            _composed_download_url(composed.video_job_id, composed.reel_id, composed.id)
            if composed.output_filename
            else None
        ),
        created_at=composed.created_at,
    )


def _load_composed(db: Session, job_id: int, reel_id: int, composed_id: int) -> tuple[VideoJob, ComposedReel]:
    job, _ = _load_reel(db, job_id, reel_id)
    composed = (
        db.query(ComposedReel)
        .filter(
            ComposedReel.id == composed_id,
            ComposedReel.reel_id == reel_id,
            ComposedReel.video_job_id == job_id,
        )
        .first()
    )
    if composed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Composed reel {composed_id} not found for reel {reel_id}",
        )
    return job, composed


@router.post(
    "/{job_id}/highlights/{reel_id}/compose",
    response_model=ComposedReelResponse,
    status_code=status.HTTP_201_CREATED,
)
def compose_highlight_reel(
    job_id: int,
    reel_id: int,
    aspect_ratio: Annotated[str | None, Query()] = None,
    music_track: Annotated[str | None, Query()] = None,
    include_intro: Annotated[bool, Query()] = True,
    include_stats: Annotated[bool, Query()] = True,
    include_watermark: Annotated[bool, Query()] = True,
    db: Session = Depends(get_db),
) -> ComposedReelResponse:
    job, _ = _load_reel(db, job_id, reel_id)
    try:
        composed = compose_reel(
            db=db,
            job_id=job_id,
            reel_id=reel_id,
            aspect_ratio=aspect_ratio,
            music_track=music_track,
            include_intro=include_intro,
            include_stats=include_stats,
            include_watermark=include_watermark,
        )
        return _composed_to_response(job.team_id, composed)
    except ReelNotReadyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (CompositionRequestError, MusicUnavailableError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (CompositionError, FFmpegError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Reel composition failed: {exc}",
        ) from exc


@router.get(
    "/{job_id}/highlights/{reel_id}/compose/{composed_id}",
    response_model=ComposedReelStatusResponse,
)
def get_composed_reel(
    job_id: int,
    reel_id: int,
    composed_id: int,
    db: Session = Depends(get_db),
) -> ComposedReelStatusResponse:
    job, composed = _load_composed(db, job_id, reel_id, composed_id)

    file_size_bytes: int | None = None
    if composed.output_path:
        output_path = Path(composed.output_path)
        if output_path.exists():
            file_size_bytes = output_path.stat().st_size

    base = _composed_to_response(job.team_id, composed)
    return ComposedReelStatusResponse(
        **base.model_dump(),
        file_size_bytes=file_size_bytes,
        error_message=composed.error_message,
    )


@router.get("/{job_id}/highlights/{reel_id}/compose/{composed_id}/download")
def download_composed_reel(
    job_id: int,
    reel_id: int,
    composed_id: int,
    db: Session = Depends(get_db),
):
    _, composed = _load_composed(db, job_id, reel_id, composed_id)
    if not composed.output_path:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Composed reel {composed_id} is not ready (status={composed.status})",
        )
    output_path = Path(composed.output_path)
    if not output_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Composed reel file not found")
    return FileResponse(
        path=str(output_path),
        media_type="video/mp4",
        filename=composed.output_filename or output_path.name,
    )

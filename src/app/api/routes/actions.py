"""Action detection endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.cv.actions import ActionRecognizer
from app.cv.schemas import ActionDetectionResponse, ActionDetectionSuggestion
from app.db.models import VideoJob
from app.db.session import get_db

router = APIRouter(prefix="/api/videos", tags=["actions"])


@router.post("/{job_id}/actions/auto")
async def auto_detect_actions(
    job_id: int,
    min_confidence: Annotated[float, Query(ge=0.0, le=1.0)] = 0.8,
    max_actions: Annotated[int, Query(ge=1, le=500)] = 50,
    mapped_only: bool = False,
    db: Session = Depends(get_db),
) -> ActionDetectionResponse:
    job = db.query(VideoJob).filter(VideoJob.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail=f"VideoJob {job_id} not found")

    try:
        candidates = ActionRecognizer.detect_actions_from_video(db=db, video_job_id=job_id)
        ActionRecognizer.persist_action_detections(db=db, video_job_id=job_id, action_candidates=candidates)

        suggestions = [
            ActionDetectionSuggestion(
                track_id=c.track_id,
                action_type=c.action_type,
                action_confidence=c.action_confidence,
                start_frame=c.start_frame,
                end_frame=c.end_frame,
                start_timestamp_sec=c.start_timestamp_sec,
                end_timestamp_sec=c.end_timestamp_sec,
                mapped_player_id=c.mapped_player_id,
            )
            for c in candidates
        ]

        suggestions = [s for s in suggestions if s.action_confidence >= min_confidence]
        if mapped_only:
            suggestions = [s for s in suggestions if s.mapped_player_id is not None]

        suggestions = sorted(
            suggestions,
            key=lambda s: (s.action_confidence, s.end_frame - s.start_frame),
            reverse=True,
        )[:max_actions]

        high_conf = sum(1 for s in suggestions if s.action_confidence >= 0.8)
        medium_conf = sum(1 for s in suggestions if 0.6 <= s.action_confidence < 0.8)
        low_conf = sum(1 for s in suggestions if s.action_confidence < 0.6)

        return ActionDetectionResponse(
            job_id=job_id,
            team_id=job.team_id,
            total_actions=len(suggestions),
            high_confidence_count=high_conf,
            medium_confidence_count=medium_conf,
            low_confidence_count=low_conf,
            actions=suggestions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Action detection failed: {exc}") from exc

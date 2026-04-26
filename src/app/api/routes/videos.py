from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.cv.schemas import VideoJobStatusResponse, VideoUploadResponse
from app.cv.storage import parse_allowed_extensions, save_upload_file
from app.cv.video_processor import process_video_job
from app.db.models.team import Team
from app.db.models.video_job import VideoJob
from app.db.session import get_db

router = APIRouter(prefix="/api/videos", tags=["videos"])


def _calculate_progress_percent(total_frames: int | None, processed_frames: int) -> float | None:
    if total_frames is None or total_frames <= 0:
        return None

    progress_percent = (processed_frames / total_frames) * 100.0
    return round(min(progress_percent, 100.0), 1)


@router.post("/upload", response_model=VideoUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    team_id: int = Form(...),
    db: Session = Depends(get_db),
) -> VideoUploadResponse:
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Team with id={team_id} was not found.")

    try:
        source_filename, storage_path = await save_upload_file(
            upload_file=file,
            storage_dir=settings.video_storage_dir,
            max_size_mb=settings.max_upload_size_mb,
            allowed_extensions=parse_allowed_extensions(settings.allowed_video_extensions),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    job = VideoJob(
        team_id=team_id,
        status="pending",
        source_filename=source_filename,
        storage_path=storage_path,
        tracker_name=settings.cv_tracker,
        model_name=settings.cv_model_path,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(process_video_job, job.id)

    return VideoUploadResponse(
        job_id=job.id,
        status=job.status,
        message="Upload accepted and processing started asynchronously.",
    )


@router.get("/{job_id}", response_model=VideoJobStatusResponse)
def get_video_job_status(job_id: int, db: Session = Depends(get_db)) -> VideoJobStatusResponse:
    job = db.get(VideoJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job with id={job_id} was not found.")

    return VideoJobStatusResponse(
        job_id=job.id,
        team_id=job.team_id,
        status=job.status,
        source_filename=job.source_filename,
        tracker_name=job.tracker_name,
        model_name=job.model_name,
        total_frames=job.total_frames,
        processed_frames=job.processed_frames,
        progress_percent=_calculate_progress_percent(job.total_frames, job.processed_frames),
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )

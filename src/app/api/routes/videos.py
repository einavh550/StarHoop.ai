from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.cv.schemas import ColabDetectionBatch, VideoJobStatusResponse, VideoUploadResponse
from app.cv.storage import parse_allowed_extensions, save_upload_file
from app.db.models.detection_frame import DetectionFrame
from app.db.models.team import Team
from app.db.models.video_job import VideoJob
from app.db.session import get_db

router = APIRouter(prefix="/api/videos", tags=["videos"])


def _calculate_progress_percent(total_frames: int | None, processed_frames: int) -> float | None:
    if total_frames is None or total_frames <= 0:
        return None

    progress_percent = (processed_frames / total_frames) * 100.0
    return round(min(progress_percent, 100.0), 1)


def _calculate_processing_duration_sec(created_at, updated_at) -> float | None:
    duration = (updated_at - created_at).total_seconds()
    if duration < 0:
        return None
    return round(duration, 1)


def _calculate_throughput_fps(processed_frames: int, processing_duration_sec: float | None) -> float | None:
    if processing_duration_sec is None or processing_duration_sec <= 0:
        return None

    return round(processed_frames / processing_duration_sec, 2)


@router.post("/upload", response_model=VideoUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_video(
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

    return VideoUploadResponse(
        job_id=job.id,
        status=job.status,
        message="Upload accepted. Awaiting Colab GPU processing via ngrok tunnel.",
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
        processing_duration_sec=_calculate_processing_duration_sec(job.created_at, job.updated_at),
        throughput_fps=_calculate_throughput_fps(
            job.processed_frames,
            _calculate_processing_duration_sec(job.created_at, job.updated_at),
        ),
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.get("/{job_id}/ocr/debug/crop")
def debug_ocr_crop(
    job_id: int,
    frame_number: int,
    track_id: int,
    db: Session = Depends(get_db),
) -> Response:
    job = db.get(VideoJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job with id={job_id} was not found.")

    frame_row = (
        db.query(DetectionFrame)
        .filter(DetectionFrame.video_job_id == job_id, DetectionFrame.frame_number == frame_number)
        .first()
    )
    if frame_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Frame not found for job.")

    detection = None
    for item in frame_row.detections_json or []:
        if item.get("track_id") == track_id:
            detection = item
            break

    if detection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Track not found in frame.")

    bbox = detection.get("bbox") or {}
    if not bbox:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Detection bbox missing.")

    try:
        import cv2  # pyright: ignore[reportMissingImports]

        capture = cv2.VideoCapture(job.storage_path)
        if not capture.isOpened():
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not open video file.")

        try:
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
            success, frame = capture.read()
            if not success:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Could not read requested frame.")

            x1, y1, x2, y2 = int(bbox["x1"]), int(bbox["y1"]), int(bbox["x2"]), int(bbox["y2"])
            pad_x = int((x2 - x1) * 0.05)
            pad_y = int((y2 - y1) * 0.05)
            h, w = frame.shape[:2]
            x1 = max(0, x1 - pad_x)
            y1 = max(0, y1 - pad_y)
            x2 = min(w, x2 + pad_x)
            y2 = min(h, y2 + pad_y)
            crop = frame[y1:y2, x1:x2]

            if crop.size == 0:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Crop was empty.")

            success, encoded = cv2.imencode(".png", crop)
            if not success:
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not encode crop.")

            return Response(content=encoded.tobytes(), media_type="image/png")
        finally:
            capture.release()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Debug crop failed: {exc}") from exc


@router.post("/{job_id}/colab-detections", status_code=status.HTTP_202_ACCEPTED)
async def ingest_colab_detections(
    job_id: int,
    payload: ColabDetectionBatch,
    db: Session = Depends(get_db),
) -> dict:
    job = db.get(VideoJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"VideoJob {job_id} not found")

    if job.status in {"pending", "failed"}:
        job.status = "processing"

    frame_rows = []
    for frame in payload.frames:
        detections_json = []
        for det in frame.detections:
            detections_json.append(
                {
                    "class_id": det.class_id,
                    "class_name": det.class_name,
                    "confidence": det.confidence,
                    "track_id": det.track_id,
                    "bbox": det.bbox.model_dump(),
                    "team_id": det.team_id,
                    "team_name": det.team_name,
                    "jersey_number": det.jersey_number,
                    "jersey_confidence": float(det.jersey_confidence),
                    "player_id": det.player_id,
                    "player_name": det.player_name,
                }
            )

        frame_rows.append(
            {
                "video_job_id": job_id,
                "frame_number": frame.frame_number,
                "timestamp_sec": Decimal(f"{frame.timestamp_sec:.3f}"),
                "detections_json": detections_json,
            }
        )

    if frame_rows:
        stmt = insert(DetectionFrame).values(frame_rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["video_job_id", "frame_number"],
            set_={
                "timestamp_sec": stmt.excluded.timestamp_sec,
                "detections_json": stmt.excluded.detections_json,
            },
        )
        db.execute(stmt)

        job.processed_frames = (job.processed_frames or 0) + len(frame_rows)

    if payload.final_batch:
        job.status = "completed"

    db.commit()

    return {
        "job_id": job_id,
        "frames_ingested": len(frame_rows),
        "final_batch": payload.final_batch,
        "status": job.status,
    }

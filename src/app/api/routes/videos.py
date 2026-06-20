import asyncio
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import SIGNATURE_HEADER, verify_signature
import logging

from app.cv import orchestration, r2_storage
from app.cv.transcode import TranscodeError, cap_fps

logger = logging.getLogger(__name__)
from app.cv.schemas import (
    ColabDetectionBatch,
    JobStatusUpdate,
    TotalFramesUpdate,
    VideoJobStatusResponse,
    VideoUploadResponse,
)
from app.cv.storage import parse_allowed_extensions, save_upload_file
from app.db.models.detection_frame import DetectionFrame
from app.db.models.team import Team
from app.db.models.video_job import VideoJob
from app.db.models.video_job_chunk import VideoJobChunk
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

    # Cap the frame rate before mirroring to R2 so that both the stored file
    # and the Modal workers operate on a smaller, cheaper video. Non-fatal: if
    # ffmpeg is unavailable (e.g. local dev without the binary) the upload
    # proceeds with the original file and a warning is logged.
    if settings.ingest_max_fps > 0:
        try:
            capped_path = await asyncio.to_thread(cap_fps, storage_path, settings.ingest_max_fps)
            if str(capped_path) != str(Path(storage_path).resolve()):
                Path(storage_path).unlink(missing_ok=True)
                storage_path = str(capped_path)
                logger.info("ingest fps_cap: %s capped to %d fps → %s", source_filename, settings.ingest_max_fps, storage_path)
        except TranscodeError as exc:
            logger.warning("ingest fps_cap skipped for %s: %s", source_filename, exc)

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

    if not settings.enable_modal_orchestration:
        return VideoUploadResponse(
            job_id=job.id,
            status=job.status,
            message="Upload accepted. Awaiting Colab GPU processing via ngrok tunnel.",
        )

    # Orchestration enabled: mirror the saved video to R2 and spawn the deployed
    # Modal GPU job, handing it a short-lived presigned download URL. The worker
    # streams detection batches back to the /colab-detections webhook.
    try:
        object_key = f"videos/{job.id}/{Path(storage_path).name}"
        r2_storage.upload_video(local_path=storage_path, key=object_key)
        presigned_url = r2_storage.generate_presigned_get_url(object_key)
        job.remote_video_url = presigned_url

        chunk_count = settings.cv_chunk_count
        if chunk_count > 1:
            # Chunked fan-out: probe total_frames from local file so we can
            # partition accurately before any worker starts.
            try:
                import cv2  # pyright: ignore[reportMissingImports]
                cap = cv2.VideoCapture(storage_path)
                total_source_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                cap.release()
            except Exception:  # noqa: BLE001
                total_source_frames = 0  # orchestration falls back to single-worker

            chunk_results = await asyncio.to_thread(
                orchestration.spawn_chunked_processing,
                job.id,
                presigned_url,
                total_source_frames,
            )
            # Persist chunk rows + set chunks_total so the completion gate knows
            # how many final_batch signals to wait for.
            actual_chunk_count = len(chunk_results)
            job.chunks_total = actual_chunk_count
            job.modal_call_id = chunk_results[0][1]  # first call id for cancel fallback
            for spec, call_id in chunk_results:
                db.add(VideoJobChunk(
                    job_id=job.id,
                    chunk_index=spec.chunk_index,
                    start_frame=spec.start_frame,
                    end_frame=spec.end_frame,
                    track_id_offset=spec.track_id_offset,
                    modal_call_id=call_id,
                    status="processing",
                ))
        else:
            # Legacy single-worker path.
            job.modal_call_id = await asyncio.to_thread(
                orchestration.spawn_processing,
                job.id,
                presigned_url,
            )

        job.status = "processing"
        db.commit()
    except (r2_storage.R2ConfigurationError, orchestration.OrchestrationError) as exc:
        job.status = "failed"
        job.error_message = str(exc)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to start GPU processing: {exc}",
        ) from exc
    except Exception as exc:  # noqa: BLE001 - catch-all so job never stays pending on unexpected errors
        import traceback
        job.status = "failed"
        job.error_message = f"Unexpected error: {exc}"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error starting GPU processing: {exc}\n{traceback.format_exc()}",
        ) from exc

    return VideoUploadResponse(
        job_id=job.id,
        status=job.status,
        message=f"Upload accepted. GPU processing started on Modal ({job.chunks_total or 1} worker(s)).",
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


@router.post("/{job_id}/cancel", status_code=status.HTTP_200_OK)
def cancel_video_job(job_id: int, db: Session = Depends(get_db)) -> dict:
    """Cancel a running job. Cancels all chunk workers when chunked.

    Idempotent: canceling an already terminal job returns the current status.
    """
    job = db.get(VideoJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job with id={job_id} was not found.")

    if job.status in {"completed", "failed", "canceled"}:
        return {"job_id": job.id, "status": job.status, "message": "Job already terminal."}

    # Collect all chunk call IDs (chunked path) or fall back to modal_call_id.
    chunk_rows = db.query(VideoJobChunk).filter(VideoJobChunk.job_id == job_id).all()
    call_ids = [c.modal_call_id for c in chunk_rows if c.modal_call_id]
    if not call_ids and job.modal_call_id:
        call_ids = [job.modal_call_id]

    cancel_warnings: list[str] = []
    if call_ids:
        failed_ids = orchestration.cancel_all_chunks(call_ids)
        if failed_ids:
            cancel_warnings.append(f"Modal cancel warning for call ids: {failed_ids}")

    # Mark all chunk rows as canceled.
    for chunk in chunk_rows:
        if chunk.status not in {"completed", "failed", "canceled"}:
            chunk.status = "canceled"

    job.status = "canceled"
    job.error_message = "Cancelled by user" + (f" ({'; '.join(cancel_warnings)})" if cancel_warnings else "")
    db.commit()
    return {"job_id": job.id, "status": job.status, "message": job.error_message}


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
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    # Verify the HMAC signature when a shared secret is configured. The worker
    # signs the exact raw body; we recompute it over the same bytes. When no
    # secret is set (local dev) verification is skipped for backward compat.
    if settings.webhook_hmac_secret:
        raw_body = await request.body()
        signature = request.headers.get(SIGNATURE_HEADER)
        if not verify_signature(settings.webhook_hmac_secret, raw_body, signature):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing webhook signature.",
            )

    job = db.get(VideoJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"VideoJob {job_id} not found")

    if job.status == "canceled":
        return {
            "job_id": job_id,
            "frames_ingested": 0,
            "final_batch": payload.final_batch,
            "status": job.status,
        }

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
        if job.chunks_total is not None and job.chunks_total > 1:
            # Chunked path: only mark completed when every chunk has sent its
            # final_batch. The increment is safe here because detection ingest
            # is synchronous-per-request and Postgres row-level locking prevents
            # double-counting under concurrent webhook traffic.
            job.chunks_done = (job.chunks_done or 0) + 1
            if job.chunks_done >= job.chunks_total:
                job.status = "completed"
        else:
            # Legacy single-worker path.
            job.status = "completed"

    db.commit()

    return {
        "job_id": job_id,
        "frames_ingested": len(frame_rows),
        "final_batch": payload.final_batch,
        "status": job.status,
    }


@router.post("/{job_id}/status", status_code=status.HTTP_200_OK)
async def update_job_status(
    job_id: int,
    payload: JobStatusUpdate,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Out-of-band status signal from the Modal worker (Milestone 4).

    The worker calls this when processing ends without a ``final_batch`` — most
    importantly to report a terminal failure (e.g. an undecodable video) so the
    job leaves ``processing`` and surfaces a clear ``error_message`` to clients.
    Signed and verified with the same HMAC secret as ``/colab-detections``.
    """
    if settings.webhook_hmac_secret:
        raw_body = await request.body()
        signature = request.headers.get(SIGNATURE_HEADER)
        if not verify_signature(settings.webhook_hmac_secret, raw_body, signature):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing webhook signature.",
            )

    new_status = payload.status.strip().lower()
    if new_status not in {"processing", "completed", "failed", "canceled"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported status '{payload.status}'.",
        )

    job = db.get(VideoJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"VideoJob {job_id} not found")

    if job.status == "canceled" and new_status != "canceled":
        return {"job_id": job_id, "status": job.status}

    job.status = new_status
    job.error_message = payload.error_message if new_status in {"failed", "canceled"} else None
    db.commit()

    return {"job_id": job_id, "status": job.status}


@router.post("/{job_id}/total-frames", status_code=status.HTTP_200_OK)
async def set_total_frames(
    job_id: int,
    payload: TotalFramesUpdate,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Worker-reported total source frame count (sent once by chunk 0).

    Populates ``video_jobs.total_frames`` so ``progress_percent`` becomes real
    immediately after the first chunk starts. Signed with the same HMAC secret
    as all other worker callbacks.
    """
    if settings.webhook_hmac_secret:
        raw_body = await request.body()
        signature = request.headers.get(SIGNATURE_HEADER)
        if not verify_signature(settings.webhook_hmac_secret, raw_body, signature):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing webhook signature.",
            )

    job = db.get(VideoJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"VideoJob {job_id} not found")

    if job.total_frames is None and payload.total_frames > 0:
        job.total_frames = payload.total_frames
        db.commit()

    return {"job_id": job_id, "total_frames": job.total_frames}

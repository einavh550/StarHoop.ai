"""Annotated export endpoints."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.cv.annotated_export import AnnotatedExportResult, load_annotated_export_metadata, render_annotated_export
from app.cv.schemas import AnnotatedVideoExportResponse, AnnotatedVideoExportStatusResponse
from app.db.models import VideoJob
from app.db.session import get_db

router = APIRouter(prefix="/api/videos", tags=["exports"])


def _to_response(result: AnnotatedExportResult) -> AnnotatedVideoExportResponse:
    return AnnotatedVideoExportResponse(
        job_id=result.job_id,
        export_id=result.export_id,
        status=result.status,
        output_filename=result.output_filename,
        download_url=f"/api/videos/{result.job_id}/exports/annotated/{result.export_id}/download",
        created_at=result.created_at,
        total_frames=result.total_frames,
        rendered_frames=result.rendered_frames,
    )


@router.post("/{job_id}/exports/annotated", response_model=AnnotatedVideoExportResponse, status_code=status.HTTP_201_CREATED)
def create_annotated_export(job_id: int, db: Session = Depends(get_db)) -> AnnotatedVideoExportResponse:
    job = db.query(VideoJob).filter(VideoJob.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"VideoJob {job_id} not found")

    try:
        result = render_annotated_export(db=db, job_id=job_id)
        return _to_response(result)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Annotated export failed: {exc}") from exc


@router.get("/{job_id}/exports/annotated/{export_id}", response_model=AnnotatedVideoExportStatusResponse)
def get_annotated_export(job_id: int, export_id: str, db: Session = Depends(get_db)) -> AnnotatedVideoExportStatusResponse:
    job = db.query(VideoJob).filter(VideoJob.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"VideoJob {job_id} not found")

    try:
        metadata = load_annotated_export_metadata(job_id=job_id, export_id=export_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    output_path = Path(metadata["output_path"])
    file_size_bytes = output_path.stat().st_size if output_path.exists() else None

    return AnnotatedVideoExportStatusResponse(
        job_id=job_id,
        export_id=export_id,
        status=metadata.get("status", "unknown"),
        output_filename=metadata.get("output_filename", output_path.name),
        download_url=f"/api/videos/{job_id}/exports/annotated/{export_id}/download",
        created_at=metadata.get("created_at"),
        total_frames=metadata.get("total_frames"),
        rendered_frames=metadata.get("rendered_frames"),
        file_size_bytes=file_size_bytes,
    )


@router.get("/{job_id}/exports/annotated/{export_id}/download")
def download_annotated_export(job_id: int, export_id: str, db: Session = Depends(get_db)):
    job = db.query(VideoJob).filter(VideoJob.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"VideoJob {job_id} not found")

    try:
        metadata = load_annotated_export_metadata(job_id=job_id, export_id=export_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    output_path = Path(metadata["output_path"])
    if not output_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Annotated export file not found")

    return FileResponse(
        path=str(output_path),
        media_type="video/mp4",
        filename=metadata.get("output_filename", output_path.name),
    )

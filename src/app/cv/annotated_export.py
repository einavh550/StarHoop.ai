from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import settings
from app.cv.storage import ensure_storage_directory
from app.db.models import DetectionFrame, JerseyDetection, Player, VideoJob

logger = logging.getLogger(__name__)


def _import_cv2_module():
    try:
        import cv2  # pyright: ignore[reportMissingImports]
    except ImportError as exc:
        raise RuntimeError("opencv-python is not installed. Install requirements.txt dependencies first.") from exc
    return cv2


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _track_color(track_id: int) -> tuple[int, int, int]:
    palette = [
        (76, 175, 80),
        (33, 150, 243),
        (255, 193, 7),
        (244, 67, 54),
        (156, 39, 176),
        (0, 188, 212),
    ]
    return palette[track_id % len(palette)]


def format_player_label(player: Player | None, detected_jersey: int | None) -> str:
    if player is not None:
        return f"{player.full_name} #{player.jersey_number}"
    if detected_jersey is not None:
        return f"Unknown #{detected_jersey}"
    return "Unknown player"


def format_ocr_label(detected_jersey: int | None) -> str:
    if detected_jersey is None:
        return "OCR --"
    return f"OCR #{detected_jersey}"


def _draw_text_chip(
    frame,
    cv2,
    text: str,
    origin_x: int,
    origin_y: int,
    background_color: tuple[int, int, int],
    text_color: tuple[int, int, int] = (255, 255, 255),
) -> None:
    font_face = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.5
    thickness = 1
    padding_x = 6
    padding_y = 5

    (text_width, text_height), baseline = cv2.getTextSize(text, font_face, font_scale, thickness)
    chip_width = text_width + (padding_x * 2)
    chip_height = text_height + baseline + (padding_y * 2)

    x1 = max(0, origin_x)
    y1 = max(0, origin_y)
    x2 = min(frame.shape[1] - 1, x1 + chip_width)
    y2 = min(frame.shape[0] - 1, y1 + chip_height)

    cv2.rectangle(frame, (x1, y1), (x2, y2), background_color, thickness=-1)
    text_x = x1 + padding_x
    text_y = y2 - padding_y - baseline
    cv2.putText(frame, text, (text_x, text_y), font_face, font_scale, text_color, thickness, cv2.LINE_AA)


def _draw_detection_overlay(
    frame,
    cv2,
    detection: dict,
    jersey_lookup: dict[int, JerseyDetection],
    player_lookup: dict[int, Player],
) -> None:
    bbox = detection.get("bbox") or {}
    track_id = detection.get("track_id")
    if track_id is None:
        return

    try:
        x1 = int(bbox["x1"])
        y1 = int(bbox["y1"])
        x2 = int(bbox["x2"])
        y2 = int(bbox["y2"])
    except (KeyError, TypeError, ValueError):
        return

    track_color = _track_color(int(track_id))
    cv2.rectangle(frame, (x1, y1), (x2, y2), track_color, thickness=2)

    jersey_row = jersey_lookup.get(int(track_id))
    detected_jersey = detection.get("jersey_number")
    if jersey_row is not None:
        detected_jersey = jersey_row.detected_jersey_number

    mapped_player = None
    if jersey_row is not None:
        mapped_player = jersey_row.mapped_player or player_lookup.get(jersey_row.detected_jersey_number)
    elif detected_jersey is not None:
        mapped_player = player_lookup.get(int(detected_jersey))

    left_label = format_player_label(mapped_player, detected_jersey if mapped_player is None else mapped_player.jersey_number)
    right_label = format_ocr_label(detected_jersey)

    left_y = max(0, y1 - 34)
    right_y = max(0, y1 - 34)

    left_text_width = cv2.getTextSize(left_label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0][0]
    right_text_width = cv2.getTextSize(right_label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0][0]

    left_x = max(0, x1 - left_text_width - 18)
    right_x = min(frame.shape[1] - 1, x2 + 10)

    _draw_text_chip(frame, cv2, left_label, left_x, left_y, (33, 37, 41))
    _draw_text_chip(frame, cv2, right_label, right_x, right_y, (46, 125, 50))


@dataclass(frozen=True)
class AnnotatedExportResult:
    export_id: str
    job_id: int
    team_id: int
    status: str
    output_path: Path
    metadata_path: Path
    output_filename: str
    created_at: str
    total_frames: int | None
    rendered_frames: int


def render_annotated_export(db: Session, job_id: int) -> AnnotatedExportResult:
    job = db.query(VideoJob).filter(VideoJob.id == job_id).first()
    if job is None:
        raise ValueError(f"VideoJob {job_id} not found")

    cv2 = _import_cv2_module()

    frames = (
        db.query(DetectionFrame)
        .filter(DetectionFrame.video_job_id == job_id)
        .order_by(DetectionFrame.frame_number.asc())
        .all()
    )
    jersey_rows = db.query(JerseyDetection).filter(JerseyDetection.video_job_id == job_id).all()
    player_rows = db.query(Player).filter(Player.team_id == job.team_id).all()

    jersey_lookup = {row.track_id: row for row in jersey_rows}
    player_lookup = {player.jersey_number: player for player in player_rows}
    frame_lookup = {frame.frame_number: frame for frame in frames}

    export_root = Path(ensure_storage_directory(settings.annotated_export_dir)) / f"job_{job_id}"
    export_root.mkdir(parents=True, exist_ok=True)

    export_id = uuid4().hex
    output_filename = f"job_{job_id}_{export_id}.mp4"
    output_path = export_root / output_filename
    metadata_path = export_root / f"{export_id}.json"

    capture = cv2.VideoCapture(job.storage_path)
    if not capture.isOpened():
        raise ValueError(f"Could not open video file: {job.storage_path}")

    success, first_frame = capture.read()
    if not success:
        capture.release()
        raise ValueError(f"Could not read video file: {job.storage_path}")

    fps = float(capture.get(cv2.CAP_PROP_FPS) or settings.cv_target_fps or 30)
    frame_height, frame_width = first_frame.shape[:2]
    writer = cv2.VideoWriter(str(output_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (frame_width, frame_height))
    if not writer.isOpened():
        capture.release()
        raise ValueError(f"Could not create export writer at {output_path}")

    rendered_frames = 0
    frame_number = 0
    current_frame = first_frame

    try:
        while True:
            annotated_frame = current_frame.copy()
            frame_row = frame_lookup.get(frame_number)
            if frame_row is not None:
                for detection in frame_row.detections_json or []:
                    if detection.get("class_name") != "person":
                        continue
                    _draw_detection_overlay(
                        annotated_frame,
                        cv2,
                        detection,
                        jersey_lookup,
                        player_lookup,
                    )

            writer.write(annotated_frame)
            rendered_frames += 1
            frame_number += 1

            success, current_frame = capture.read()
            if not success:
                break
    except Exception:
        output_path.unlink(missing_ok=True)
        metadata_path.unlink(missing_ok=True)
        raise
    finally:
        capture.release()
        writer.release()

    metadata = {
        "export_id": export_id,
        "job_id": job.id,
        "team_id": job.team_id,
        "status": "completed",
        "output_filename": output_filename,
        "output_path": str(output_path.resolve()),
        "source_video_path": job.storage_path,
        "created_at": _utc_now_iso(),
        "total_frames": job.total_frames,
        "rendered_frames": rendered_frames,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    logger.info("annotated_export_created job_id=%s export_id=%s path=%s", job.id, export_id, output_path)

    return AnnotatedExportResult(
        export_id=export_id,
        job_id=job.id,
        team_id=job.team_id,
        status="completed",
        output_path=output_path,
        metadata_path=metadata_path,
        output_filename=output_filename,
        created_at=metadata["created_at"],
        total_frames=job.total_frames,
        rendered_frames=rendered_frames,
    )


def load_annotated_export_metadata(job_id: int, export_id: str) -> dict:
    export_root = Path(ensure_storage_directory(settings.annotated_export_dir)) / f"job_{job_id}"
    metadata_path = export_root / f"{export_id}.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"Annotated export {export_id} not found for job {job_id}")

    with metadata_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)

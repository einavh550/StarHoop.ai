from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import settings
from app.cv.mapping import PlayerMapper
from app.cv.storage import ensure_storage_directory
from app.cv.transcode import TranscodeError, normalize_video
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


def _round_box(box: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    return (int(round(box[0])), int(round(box[1])), int(round(box[2])), int(round(box[3])))


def _build_interpolated_boxes(
    frames,
    max_gap_frames: int,
    tail_frames: int,
) -> dict[int, dict[int, tuple[int, int, int, int]]]:
    """Reconstruct a smooth per-frame box for every track from sparse keyframes.

    With temporal subsampling (``cv_frame_stride``) detections only exist on
    every Nth source frame, which makes boxes flicker. Here we linearly
    interpolate each track's box across the gap between consecutive stored
    keyframes (and carry the last box forward for a short tail), so boxes stay
    on-screen and move smoothly. This is pure CPU geometry -- no GPU/AI credits.

    Returns ``{frame_number: {track_id: (x1, y1, x2, y2)}}``.
    """
    track_keyframes: dict[int, list[tuple[int, tuple[float, float, float, float]]]] = defaultdict(list)
    for frame_row in frames:
        frame_number = frame_row.frame_number
        for detection in frame_row.detections_json or []:
            class_name = (detection.get("class_name") or "").lower()
            if class_name not in {"person", "player"}:
                continue
            track_id = detection.get("track_id")
            if track_id is None:
                continue
            bbox = detection.get("bbox") or {}
            try:
                box = (float(bbox["x1"]), float(bbox["y1"]), float(bbox["x2"]), float(bbox["y2"]))
            except (KeyError, TypeError, ValueError):
                continue
            track_keyframes[int(track_id)].append((frame_number, box))

    boxes: dict[int, dict[int, tuple[int, int, int, int]]] = defaultdict(dict)
    for track_id, keyframes in track_keyframes.items():
        keyframes.sort(key=lambda item: item[0])

        # Lowest precedence: carry the final box forward a short tail so the
        # track does not disappear abruptly on the frames after its last sample.
        last_frame, last_box = keyframes[-1]
        for frame_number in range(last_frame + 1, last_frame + tail_frames + 1):
            boxes[frame_number][track_id] = _round_box(last_box)

        # Middle precedence: interpolate across small gaps between keyframes.
        for index in range(len(keyframes) - 1):
            frame_a, box_a = keyframes[index]
            frame_b, box_b = keyframes[index + 1]
            gap = frame_b - frame_a
            if 1 < gap <= max_gap_frames:
                for frame_number in range(frame_a + 1, frame_b):
                    ratio = (frame_number - frame_a) / gap
                    interpolated = tuple(
                        box_a[axis] * (1.0 - ratio) + box_b[axis] * ratio for axis in range(4)
                    )
                    boxes[frame_number][track_id] = _round_box(interpolated)

        # Highest precedence: exact stored keyframes always win.
        for frame_number, box in keyframes:
            boxes[frame_number][track_id] = _round_box(box)

    return boxes


def _resolve_track_identities(
    db: Session,
    job_id: int,
    team_id: int,
) -> dict[int, tuple[Player | None, int | None]]:
    """Vote a single stable jersey + roster player per track across the video.

    Reuses OCR results already stored in ``detection_frames`` (majority/
    confidence voting), so it spends no GPU/AI credits. The aggregated result is
    persisted to ``jersey_detections`` idempotently so diagnostics stay in sync,
    and returned as ``{track_id: (Player | None, detected_jersey | None)}`` for
    rendering a constant label on every frame of each track.
    """
    try:
        db.query(JerseyDetection).filter(JerseyDetection.video_job_id == job_id).delete()
        db.flush()
        aggregated = PlayerMapper.aggregate_jerseys_from_video(db, job_id, team_id)
        PlayerMapper.persist_jersey_detections(db, job_id, aggregated)
    except Exception:
        logger.exception(
            "jersey aggregation failed for job_id=%s; boxes will render without identity", job_id
        )
        return {}

    identities: dict[int, tuple[Player | None, int | None]] = {}
    for track_id, data in aggregated.items():
        identities[int(track_id)] = (data.get("suggested_player"), data.get("detected_jersey"))
    return identities


def _draw_track_overlay(
    frame,
    cv2,
    track_id: int,
    box: tuple[int, int, int, int],
    player: Player | None,
    jersey: int | None,
) -> None:
    x1, y1, x2, y2 = box
    track_color = _track_color(int(track_id))
    cv2.rectangle(frame, (x1, y1), (x2, y2), track_color, thickness=2)

    label = format_player_label(player, jersey if player is None else player.jersey_number)

    text_width = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0][0]
    chip_width = text_width + 12
    box_center_x = (x1 + x2) // 2
    label_x = max(0, min(box_center_x - chip_width // 2, frame.shape[1] - 1 - chip_width))
    label_y = max(0, y1 - 24)

    _draw_text_chip(frame, cv2, label, label_x, label_y, (33, 37, 41))


def _box_area(box: tuple[int, int, int, int]) -> int:
    x1, y1, x2, y2 = box
    return max(0, x2 - x1) * max(0, y2 - y1)


def select_single_box_per_player(
    track_boxes: dict[int, tuple[int, int, int, int]],
    identity_by_track: dict[int, tuple[Player | None, int | None]],
) -> dict[int, tuple[int, int, int, int]]:
    """Drop redundant boxes so each roster player is drawn at most once per frame.

    When SAM-2 fragments one player into multiple tracks, two boxes for the same
    ``#/name`` appear in a single frame (the "duplicate identity" bug). For each
    player resolved in this frame we keep only the largest-area box (the most
    confident foreground detection) and suppress the rest. Tracks with no matched
    player (``player is None``) are always kept — opponents and unknowns are not
    collapsed.
    """
    best_track_for_player: dict[int, int] = {}
    for track_id, box in track_boxes.items():
        player, _jersey = identity_by_track.get(track_id, (None, None))
        if player is None:
            continue
        current = best_track_for_player.get(player.id)
        if current is None or _box_area(box) > _box_area(track_boxes[current]):
            best_track_for_player[player.id] = track_id

    kept_player_tracks = set(best_track_for_player.values())
    selected: dict[int, tuple[int, int, int, int]] = {}
    for track_id, box in track_boxes.items():
        player, _jersey = identity_by_track.get(track_id, (None, None))
        if player is None or track_id in kept_player_tracks:
            selected[track_id] = box
    return selected


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
    annotated_player_id: int | None = None


def render_annotated_export(
    db: Session,
    job_id: int,
    *,
    annotated_player_id: int | None = None,
) -> AnnotatedExportResult:
    job = db.query(VideoJob).filter(VideoJob.id == job_id).first()
    if job is None:
        raise ValueError(f"VideoJob {job_id} not found")

    if annotated_player_id is not None:
        target_player = (
            db.query(Player)
            .filter(Player.id == annotated_player_id, Player.team_id == job.team_id)
            .first()
        )
        if target_player is None:
            raise ValueError(
                f"Player {annotated_player_id} not found on team {job.team_id} for job {job_id}"
            )

    cv2 = _import_cv2_module()

    frames = (
        db.query(DetectionFrame)
        .filter(DetectionFrame.video_job_id == job_id)
        .order_by(DetectionFrame.frame_number.asc())
        .all()
    )
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

    # OpenCV's headless build has no H.264 encoder (licensing), so we write the
    # frames with the always-available ``mp4v`` codec to a temp file and then
    # transcode that to H.264 (avc1) with ffmpeg below. The final file is the
    # broadly-playable one (Windows Media Player, etc.).
    raw_output_path = export_root / f"{export_id}_raw.mp4"
    writer = cv2.VideoWriter(str(raw_output_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (frame_width, frame_height))
    if not writer.isOpened():
        capture.release()
        raise ValueError(f"Could not create export writer at {raw_output_path}")

    # Bridge subsampling gaps up to ~0.5s and keep a short ~0.15s tail so boxes
    # stay smooth and stable instead of flickering on un-sampled frames.
    max_gap_frames = max(1, int(round(fps * 0.5)))
    tail_frames = max(1, int(round(fps * 0.15)))
    boxes_per_frame = _build_interpolated_boxes(frames, max_gap_frames, tail_frames)
    identity_by_track = _resolve_track_identities(db, job_id, job.team_id)

    rendered_frames = 0
    frame_number = 0
    current_frame = first_frame

    try:
        while True:
            annotated_frame = current_frame.copy()
            track_boxes = boxes_per_frame.get(frame_number)
            if track_boxes and settings.track_consolidation:
                # Fix 1: collapse fragmented tracks so a player is boxed once.
                track_boxes = select_single_box_per_player(track_boxes, identity_by_track)
            if track_boxes:
                for track_id, box in track_boxes.items():
                    player, jersey = identity_by_track.get(track_id, (None, None))
                    if annotated_player_id is not None:
                        if player is None or player.id != annotated_player_id:
                            continue
                    _draw_track_overlay(annotated_frame, cv2, track_id, box, player, jersey)

            writer.write(annotated_frame)
            rendered_frames += 1
            frame_number += 1

            success, current_frame = capture.read()
            if not success:
                break
    except Exception:
        raw_output_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)
        metadata_path.unlink(missing_ok=True)
        raise
    finally:
        capture.release()
        writer.release()

    # Transcode the raw mp4v file to H.264 so it plays everywhere. If ffmpeg is
    # unavailable we fall back to the mp4v file rather than failing the export.
    try:
        normalize_video(raw_output_path, output_path)
        raw_output_path.unlink(missing_ok=True)
    except TranscodeError:
        logger.warning(
            "ffmpeg unavailable; annotated export %s left as mp4v (less compatible)",
            export_id,
        )
        raw_output_path.replace(output_path)

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
        "annotated_player_id": annotated_player_id,
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
        annotated_player_id=annotated_player_id,
    )


def load_annotated_export_metadata(job_id: int, export_id: str) -> dict:
    export_root = Path(ensure_storage_directory(settings.annotated_export_dir)) / f"job_{job_id}"
    metadata_path = export_root / f"{export_id}.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"Annotated export {export_id} not found for job {job_id}")

    with metadata_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)

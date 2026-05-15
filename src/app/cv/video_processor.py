from datetime import datetime, timezone
from decimal import Decimal
import logging

from sqlalchemy.orm import Session

from app.core.config import settings
from app.cv.detection import YOLODetector
from app.cv.ocr import JerseyRecognizer
from app.cv.tracking import build_tracker
from app.db.models.detection_frame import DetectionFrame
from app.db.models.video_job import VideoJob
from app.db.session import SessionLocal


logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _import_cv2_module():
    try:
        import cv2  # pyright: ignore[reportMissingImports]
    except ImportError as exc:
        raise RuntimeError("opencv-python is not installed. Install requirements.txt dependencies first.") from exc
    return cv2


def _to_decimal_seconds(raw_value: float) -> Decimal:
    return Decimal(f"{raw_value:.3f}")


class VideoProcessor:
    def __init__(self, detector: YOLODetector, target_fps: int, jersey_recognizer: JerseyRecognizer | None = None) -> None:
        self.detector = detector
        self.target_fps = max(target_fps, 1)
        self.jersey_recognizer = jersey_recognizer or JerseyRecognizer(confidence_threshold=settings.ocr_confidence_threshold)

    def process_job(self, db: Session, job: VideoJob) -> None:
        cv2 = _import_cv2_module()

        capture = cv2.VideoCapture(job.storage_path)
        if not capture.isOpened():
            raise ValueError(f"Could not open video file: {job.storage_path}")

        native_fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        if native_fps <= 0:
            native_fps = float(self.target_fps)

        frame_interval = max(int(round(native_fps / float(self.target_fps))), 1)
        job.total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

        tracker = build_tracker(job.tracker_name)

        frame_index = 0
        processed_frames = 0
        ocr_attempts = 0
        ocr_hits = 0
        ocr_rejections = 0
        ocr_failures = 0

        try:
            while True:
                success, frame = capture.read()
                if not success:
                    break

                if frame_index % frame_interval != 0:
                    frame_index += 1
                    continue

                timestamp_sec = frame_index / native_fps
                detected_frame = self.detector.detect_players(
                    frame=frame,
                    frame_number=frame_index,
                    timestamp_sec=timestamp_sec,
                )
                tracked_detections = tracker.update(detected_frame.detections)

                detection_payload = []
                for detection in tracked_detections:
                    # Extract jersey number from the bounding box crop
                    jersey_num = None
                    jersey_conf = 0.0
                    jersey_ocr_status = "not_attempted"
                    jersey_ocr_reason = "not_attempted"
                    ocr_attempts += 1
                    try:
                        bbox_crop = self.jersey_recognizer.preprocess_bbox_crop(
                            frame=frame,
                            bbox=detection.bbox.model_dump(),
                            pad_percent=0.05
                        )
                        crop_h, crop_w = bbox_crop.shape[:2]
                        jersey_num, jersey_conf = self.jersey_recognizer.extract_jersey_from_bbox(
                            bbox_crop,
                            allow_low_confidence=settings.ocr_persist_low_confidence,
                        )
                        jersey_ocr_reason = self.jersey_recognizer.last_ocr_reason
                        if jersey_num is not None:
                            jersey_ocr_status = "hit"
                            ocr_hits += 1
                            logger.info(
                                "ocr_hit job_id=%s track_id=%s jersey=%s conf=%.3f crop=%sx%s frame=%s",
                                job.id,
                                detection.track_id,
                                jersey_num,
                                jersey_conf,
                                crop_w,
                                crop_h,
                                frame_index,
                            )
                        else:
                            jersey_ocr_status = "miss"
                            ocr_rejections += 1
                            logger.info(
                                "ocr_reject job_id=%s track_id=%s conf=%.3f threshold=%.3f crop=%sx%s frame=%s",
                                job.id,
                                detection.track_id,
                                jersey_conf,
                                self.jersey_recognizer.confidence_threshold,
                                crop_w,
                                crop_h,
                                frame_index,
                            )
                    except Exception as exc:
                        # Jersey extraction failed; log but don't block pipeline
                        jersey_ocr_status = "failure"
                        jersey_ocr_reason = f"exception:{exc.__class__.__name__}"
                        ocr_failures += 1
                        logger.warning(
                            "ocr_failure job_id=%s track_id=%s frame=%s error=%s",
                            job.id,
                            detection.track_id,
                            frame_index,
                            exc,
                        )
                    
                    detection_payload.append(
                        {
                            "class_id": detection.class_id,
                            "class_name": detection.class_name,
                            "confidence": detection.confidence,
                            "track_id": detection.track_id,
                            "bbox": detection.bbox.model_dump(),
                            "jersey_number": jersey_num,
                            "jersey_confidence": float(jersey_conf),
                            "jersey_ocr_status": jersey_ocr_status,
                            "jersey_ocr_reason": jersey_ocr_reason,
                        }
                    )

                db.add(
                    DetectionFrame(
                        video_job_id=job.id,
                        frame_number=frame_index,
                        timestamp_sec=_to_decimal_seconds(timestamp_sec),
                        detections_json=detection_payload,
                    )
                )

                processed_frames += 1
                job.processed_frames = processed_frames
                job.updated_at = utc_now()

                if processed_frames % 30 == 0:
                    db.commit()

                frame_index += 1

            db.commit()
            logger.info(
                "ocr_summary job_id=%s attempts=%s hits=%s rejections=%s failures=%s hit_rate=%.3f",
                job.id,
                ocr_attempts,
                ocr_hits,
                ocr_rejections,
                ocr_failures,
                (ocr_hits / ocr_attempts) if ocr_attempts else 0.0,
            )
        finally:
            capture.release()


def reprocess_jersey_detections_from_video(db: Session, job: VideoJob) -> dict[str, int]:
    cv2 = _import_cv2_module()
    recognizer = JerseyRecognizer(confidence_threshold=settings.ocr_confidence_threshold)

    frames = (
        db.query(DetectionFrame)
        .filter(DetectionFrame.video_job_id == job.id)
        .order_by(DetectionFrame.frame_number.asc())
        .all()
    )
    if not frames:
        return {"frames": 0, "updated": 0, "hits": 0, "rejections": 0, "failures": 0}

    capture = cv2.VideoCapture(job.storage_path)
    if not capture.isOpened():
        raise ValueError(f"Could not open video file: {job.storage_path}")

    updated = 0
    hits = 0
    rejections = 0
    failures = 0
    try:
        for frame_row in frames:
            capture.set(cv2.CAP_PROP_POS_FRAMES, int(frame_row.frame_number))
            success, frame = capture.read()
            if not success:
                failures += 1
                continue

            changed = False
            detections_json = frame_row.detections_json or []
            for detection in detections_json:
                if detection.get("class_name") != "person" or detection.get("track_id") is None:
                    continue

                if detection.get("jersey_number") is not None and detection.get("jersey_confidence", 0.0) >= settings.ocr_confidence_threshold:
                    continue

                try:
                    bbox_crop = recognizer.preprocess_bbox_crop(frame=frame, bbox=detection["bbox"], pad_percent=0.05)
                    jersey_num, jersey_conf = recognizer.extract_jersey_from_bbox(
                        bbox_crop,
                        allow_low_confidence=settings.ocr_persist_low_confidence,
                    )
                    detection["jersey_number"] = jersey_num
                    detection["jersey_confidence"] = float(jersey_conf)
                    detection["jersey_ocr_status"] = "hit" if jersey_num is not None else "miss"
                    detection["jersey_ocr_reason"] = recognizer.last_ocr_reason
                    changed = True
                    if jersey_num is not None:
                        hits += 1
                    else:
                        rejections += 1
                except Exception:
                    failures += 1
                    continue

            if changed:
                frame_row.detections_json = detections_json
                updated += 1

        db.commit()
        return {"frames": len(frames), "updated": updated, "hits": hits, "rejections": rejections, "failures": failures}
    finally:
        capture.release()


def process_video_job(video_job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.get(VideoJob, video_job_id)
        if job is None:
            return

        job.status = "processing"
        job.error_message = None
        job.updated_at = utc_now()
        db.commit()
        db.refresh(job)

        detector = YOLODetector(
            model_path=settings.cv_model_path,
            confidence_threshold=settings.cv_confidence_threshold,
            min_player_height_px=settings.cv_min_player_height_px,
        )
        processor = VideoProcessor(detector=detector, target_fps=settings.cv_target_fps)
        processor.process_job(db=db, job=job)

        job.status = "completed"
        job.updated_at = utc_now()
        db.commit()
    except Exception as exc:
        db.rollback()
        failed_job = db.get(VideoJob, video_job_id)
        if failed_job is not None:
            failed_job.status = "failed"
            failed_job.error_message = str(exc)[:2000]
            failed_job.updated_at = utc_now()
            db.commit()
    finally:
        db.close()

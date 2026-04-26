from typing import Any

from app.cv.schemas import BoundingBox, Detection, DetectionFramePayload


class YOLODetector:
    def __init__(self, model_path: str, confidence_threshold: float, min_player_height_px: int) -> None:
        self.model_path = model_path
        self.confidence_threshold = confidence_threshold
        self.min_player_height_px = min_player_height_px
        self._model: Any = None

    def _load_model(self) -> Any:
        if self._model is None:
            try:
                from ultralytics import YOLO  # pyright: ignore[reportMissingImports]
            except ImportError as exc:
                raise RuntimeError(
                    "ultralytics is not installed. Install dependencies from requirements.txt first."
                ) from exc
            self._model = YOLO(self.model_path)
        return self._model

    def detect_players(self, frame: Any, frame_number: int, timestamp_sec: float) -> DetectionFramePayload:
        payload = DetectionFramePayload(frame_number=frame_number, timestamp_sec=timestamp_sec)
        model = self._load_model()
        results = model.predict(source=frame, conf=self.confidence_threshold, verbose=False)

        if not results:
            return payload

        boxes = getattr(results[0], "boxes", None)
        if boxes is None:
            return payload

        for box in boxes:
            class_id = int(box.cls[0].item())
            if class_id != 0:
                continue

            confidence = float(box.conf[0].item())
            x1, y1, x2, y2 = [float(value) for value in box.xyxy[0].tolist()]

            if (y2 - y1) < self.min_player_height_px:
                continue

            payload.detections.append(
                Detection(
                    class_id=class_id,
                    class_name="person",
                    confidence=confidence,
                    bbox=BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2),
                )
            )

        return payload

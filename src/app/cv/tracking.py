from typing import Protocol

from app.cv.schemas import BoundingBox, Detection


class Tracker(Protocol):
    def update(self, detections: list[Detection]) -> list[Detection]:
        ...


def _intersection_over_union(box_a: BoundingBox, box_b: BoundingBox) -> float:
    x_left = max(box_a.x1, box_b.x1)
    y_top = max(box_a.y1, box_b.y1)
    x_right = min(box_a.x2, box_b.x2)
    y_bottom = min(box_a.y2, box_b.y2)

    if x_right <= x_left or y_bottom <= y_top:
        return 0.0

    intersection_area = (x_right - x_left) * (y_bottom - y_top)
    area_a = (box_a.x2 - box_a.x1) * (box_a.y2 - box_a.y1)
    area_b = (box_b.x2 - box_b.x1) * (box_b.y2 - box_b.y1)
    denominator = area_a + area_b - intersection_area
    if denominator <= 0:
        return 0.0

    return intersection_area / denominator


class ByteTrackTracker:
    def __init__(self, iou_threshold: float = 0.3, max_missing_frames: int = 15) -> None:
        self.iou_threshold = iou_threshold
        self.max_missing_frames = max_missing_frames
        self._next_track_id = 1
        self._active_boxes: dict[int, BoundingBox] = {}
        self._missing_counts: dict[int, int] = {}

    def update(self, detections: list[Detection]) -> list[Detection]:
        matched_track_ids: set[int] = set()
        remaining_track_ids = set(self._active_boxes.keys())

        for detection in detections:
            best_track_id: int | None = None
            best_iou = 0.0

            for track_id in remaining_track_ids:
                current_iou = _intersection_over_union(self._active_boxes[track_id], detection.bbox)
                if current_iou >= self.iou_threshold and current_iou > best_iou:
                    best_iou = current_iou
                    best_track_id = track_id

            if best_track_id is None:
                best_track_id = self._next_track_id
                self._next_track_id += 1
            else:
                remaining_track_ids.remove(best_track_id)

            detection.track_id = best_track_id
            self._active_boxes[best_track_id] = detection.bbox
            self._missing_counts[best_track_id] = 0
            matched_track_ids.add(best_track_id)

        for track_id in list(self._active_boxes.keys()):
            if track_id in matched_track_ids:
                continue
            self._missing_counts[track_id] = self._missing_counts.get(track_id, 0) + 1
            if self._missing_counts[track_id] > self.max_missing_frames:
                self._active_boxes.pop(track_id, None)
                self._missing_counts.pop(track_id, None)

        return detections


class DeepSortTracker:
    def update(self, detections: list[Detection]) -> list[Detection]:
        raise NotImplementedError(
            "DeepSORT adapter is scaffolded but not implemented yet. "
            "Set CV_TRACKER=bytetrack for Milestone 2."
        )


def build_tracker(tracker_name: str) -> Tracker:
    normalized = tracker_name.strip().lower()
    if normalized in {"bytetrack", "byte-track", "byte_track"}:
        return ByteTrackTracker()
    if normalized in {"deepsort", "deep-sort", "deep_sort"}:
        return DeepSortTracker()
    raise ValueError(f"Unsupported tracker '{tracker_name}'.")

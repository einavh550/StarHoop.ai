import pytest

from app.cv.schemas import BoundingBox, Detection
from app.cv.tracking import ByteTrackTracker, DeepSortTracker, build_tracker


def _make_detection(x1: float, y1: float, x2: float, y2: float) -> Detection:
    return Detection(
        class_id=0,
        class_name="person",
        confidence=0.9,
        bbox=BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2),
    )


def test_build_tracker_returns_bytetrack() -> None:
    tracker = build_tracker("bytetrack")
    assert isinstance(tracker, ByteTrackTracker)


def test_build_tracker_returns_deepsort_scaffold() -> None:
    tracker = build_tracker("deepsort")
    assert isinstance(tracker, DeepSortTracker)



def test_deepsort_scaffold_raises_on_use() -> None:
    tracker = build_tracker("deepsort")
    with pytest.raises(NotImplementedError):
        tracker.update([])


def test_bytetrack_preserves_track_id_for_similar_boxes() -> None:
    tracker = ByteTrackTracker(iou_threshold=0.1)

    first = tracker.update([_make_detection(0, 0, 100, 200)])[0]
    second = tracker.update([_make_detection(5, 5, 105, 205)])[0]

    assert first.track_id is not None
    assert second.track_id == first.track_id

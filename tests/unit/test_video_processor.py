from app.cv.schemas import BoundingBox, Detection, DetectionFramePayload
from app.cv.video_processor import VideoProcessor
from app.db.models.video_job import VideoJob


class _FakeCapture:
    def __init__(self) -> None:
        self._frames = [object(), object()]
        self._cursor = 0

    def isOpened(self) -> bool:
        return True

    def get(self, prop: int) -> float:
        if prop == 5:
            return 30.0
        if prop == 7:
            return float(len(self._frames))
        return 0.0

    def read(self):
        if self._cursor >= len(self._frames):
            return False, None
        frame = self._frames[self._cursor]
        self._cursor += 1
        return True, frame

    def release(self) -> None:
        return None


class _FakeCV2:
    CAP_PROP_FPS = 5
    CAP_PROP_FRAME_COUNT = 7

    def __init__(self, capture: _FakeCapture) -> None:
        self._capture = capture

    def VideoCapture(self, _path: str) -> _FakeCapture:
        return self._capture


class _FakeDetector:
    def detect_players(self, frame, frame_number: int, timestamp_sec: float) -> DetectionFramePayload:
        return DetectionFramePayload(
            frame_number=frame_number,
            timestamp_sec=timestamp_sec,
            detections=[
                Detection(
                    class_id=0,
                    class_name="person",
                    confidence=0.9,
                    bbox=BoundingBox(x1=0, y1=0, x2=100, y2=200),
                )
            ],
        )


class _FakeTracker:
    def update(self, detections: list[Detection]) -> list[Detection]:
        for index, detection in enumerate(detections, start=1):
            detection.track_id = index
        return detections


class _FakeDB:
    def __init__(self) -> None:
        self.added = []
        self.commit_calls = 0

    def add(self, obj) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        self.commit_calls += 1


def test_video_processor_persists_detection_frames(monkeypatch) -> None:
    fake_capture = _FakeCapture()
    fake_cv2 = _FakeCV2(fake_capture)
    fake_db = _FakeDB()

    monkeypatch.setattr("app.cv.video_processor._import_cv2_module", lambda: fake_cv2)
    monkeypatch.setattr("app.cv.video_processor.build_tracker", lambda _name: _FakeTracker())

    job = VideoJob(
        id=1,
        team_id=1,
        status="processing",
        source_filename="sample.mp4",
        storage_path="C:/tmp/sample.mp4",
        tracker_name="bytetrack",
        model_name="yolov8n.pt",
        processed_frames=0,
    )

    processor = VideoProcessor(detector=_FakeDetector(), target_fps=30)
    processor.process_job(db=fake_db, job=job)

    assert job.total_frames == 2
    assert job.processed_frames == 2
    assert len(fake_db.added) == 2
    assert fake_db.commit_calls >= 1

from datetime import datetime

from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float


class Detection(BaseModel):
    class_id: int
    class_name: str
    confidence: float
    bbox: BoundingBox
    track_id: int | None = None
    jersey_number: int | None = None
    jersey_confidence: float = 0.0


class DetectionFramePayload(BaseModel):
    frame_number: int
    timestamp_sec: float
    detections: list[Detection] = Field(default_factory=list)


class VideoUploadResponse(BaseModel):
    job_id: int
    status: str
    message: str


class VideoJobStatusResponse(BaseModel):
    job_id: int
    team_id: int
    status: str
    source_filename: str
    tracker_name: str
    model_name: str
    total_frames: int | None = None
    processed_frames: int = 0
    progress_percent: float | None = None
    processing_duration_sec: float | None = None
    throughput_fps: float | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

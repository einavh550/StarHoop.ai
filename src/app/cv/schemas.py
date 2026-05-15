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


class PlayerMappingSuggestion(BaseModel):
    """Suggested player mapping for a detected track_id."""
    track_id: int
    detected_jersey: int
    frame_count: int
    confidence_mean: float
    confidence_max: float
    suggested_player_id: int | None = None
    suggested_player_name: str | None = None
    match_rating: str  # 'high', 'medium', 'low', 'no_match'


class PlayerMappingResponse(BaseModel):
    """Player mapping suggestions for a video job."""
    job_id: int
    team_id: int
    total_mappings: int
    high_confidence_count: int
    medium_confidence_count: int
    low_confidence_count: int
    no_match_count: int
    mappings: list[PlayerMappingSuggestion] = Field(default_factory=list)


class AnnotatedVideoExportResponse(BaseModel):
    job_id: int
    export_id: str
    status: str
    output_filename: str
    download_url: str
    created_at: str
    total_frames: int | None = None
    rendered_frames: int = 0


class AnnotatedVideoExportStatusResponse(AnnotatedVideoExportResponse):
    file_size_bytes: int | None = None


class ActionDetectionSuggestion(BaseModel):
    track_id: int | None = None
    action_type: str
    action_confidence: float
    start_frame: int
    end_frame: int
    start_timestamp_sec: float
    end_timestamp_sec: float
    mapped_player_id: int | None = None


class ActionDetectionResponse(BaseModel):
    job_id: int
    team_id: int
    total_actions: int
    high_confidence_count: int
    medium_confidence_count: int
    low_confidence_count: int
    actions: list[ActionDetectionSuggestion] = Field(default_factory=list)

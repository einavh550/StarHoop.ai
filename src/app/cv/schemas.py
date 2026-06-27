from datetime import datetime

from pydantic import BaseModel, Field


class PlayerDto(BaseModel):
    player_id: int
    team_id: int
    jersey_number: int
    full_name: str
    photo_url: str | None = None
    birth_year: int | None = None


class TeamDto(BaseModel):
    team_id: int
    name: str
    season: str
    logo_url: str | None = None
    players: list[PlayerDto] = Field(default_factory=list)


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


class ColabBoundingBox(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float

    class Config:
        extra = "forbid"


class ColabDetection(BaseModel):
    track_id: int
    bbox: ColabBoundingBox
    class_id: int | None = None
    class_name: str | None = None
    confidence: float | None = None
    team_id: int | None = None
    team_name: str | None = None
    jersey_number: int | None = None
    jersey_confidence: float = 0.0
    player_id: int | None = None
    player_name: str | None = None

    class Config:
        extra = "forbid"


class ColabFramePayload(BaseModel):
    frame_number: int
    timestamp_sec: float
    detections: list[ColabDetection] = Field(default_factory=list)

    class Config:
        extra = "forbid"


class ColabDetectionBatch(BaseModel):
    batch_id: str | None = None
    source: str | None = "colab"
    final_batch: bool = False
    frames: list[ColabFramePayload] = Field(default_factory=list)

    class Config:
        extra = "forbid"


class JobStatusUpdate(BaseModel):
    """Out-of-band job status signal POSTed by the Modal worker.

    Lets the worker report a terminal failure (e.g. a video it could not decode)
    so the API flips the job to ``failed`` with a human-readable message instead
    of leaving it stuck on ``processing``.
    """

    status: str
    error_message: str | None = None
    chunk_index: int | None = None

    class Config:
        extra = "forbid"


class TotalFramesUpdate(BaseModel):
    """Worker-reported total source frame count (sent once by chunk 0).

    Enables real ``progress_percent`` reporting from the first batch onward.
    """

    total_frames: int

    class Config:
        extra = "forbid"


class VideoUploadResponse(BaseModel):
    job_id: int
    status: str
    message: str


class AssetUploadResponse(BaseModel):
    asset_type: str
    original_filename: str
    stored_filename: str
    storage_key: str
    download_url: str | None = None
    message: str


class PlayerPhotoUploadResponse(AssetUploadResponse):
    team_id: int
    jersey_number: int
    player_id: int
    player_name: str
    photo_url: str


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


class HighlightClipResponse(BaseModel):
    clip_id: int
    order_index: int
    event_type: str
    source: str
    track_id: int | None = None
    mapped_player_id: int | None = None
    start_frame: int
    end_frame: int
    start_timestamp_sec: float
    end_timestamp_sec: float
    made: bool | None = None
    score: float
    confidence: float
    clip_filename: str | None = None
    download_url: str | None = None


class HighlightReelResponse(BaseModel):
    reel_id: int
    job_id: int
    team_id: int
    status: str
    scope: str
    source_mode: str
    player_id: int | None = None
    clip_count: int
    total_duration_sec: float
    output_filename: str | None = None
    download_url: str | None = None
    created_at: datetime
    clips: list[HighlightClipResponse] = Field(default_factory=list)


class HighlightReelStatusResponse(HighlightReelResponse):
    file_size_bytes: int | None = None
    error_message: str | None = None


class ComposedReelResponse(BaseModel):
    composed_reel_id: int
    reel_id: int
    job_id: int
    team_id: int
    player_id: int | None = None
    status: str
    aspect_ratio: str
    music_track: str | None = None
    has_intro: bool
    has_stats: bool
    has_watermark: bool
    total_duration_sec: float
    output_filename: str | None = None
    download_url: str | None = None
    created_at: datetime


class ComposedReelStatusResponse(ComposedReelResponse):
    file_size_bytes: int | None = None
    error_message: str | None = None


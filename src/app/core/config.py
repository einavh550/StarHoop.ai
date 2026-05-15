from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/starhoop"
    test_database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/starhoop"
    app_env: str = "development"

    cv_model_path: str = "yolov8n.pt"
    cv_confidence_threshold: float = 0.5
    cv_min_player_height_px: int = 50
    cv_tracker: str = "bytetrack"
    cv_target_fps: int = 30
    ocr_confidence_threshold: float = 0.5
    ocr_persist_low_confidence: bool = False
    ocr_confidence_strict: float = 0.75
    jersey_aggregation_min_frames: int = 3
    jersey_aggregation_outlier_threshold: float = 0.6
    ocr_debug_crop_dump_dir: str = "uploads/ocr_debug"
    ocr_min_crop_size_px: int = 12
    ocr_resize_height_px: int = 64

    max_upload_size_mb: int = 500
    video_storage_dir: str = "uploads/videos"
    annotated_export_dir: str = "uploads/annotated_exports"
    allowed_video_extensions: str = ".mp4,.mov,.avi,.mkv"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()

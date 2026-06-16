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

    max_upload_size_mb: int = 600
    video_storage_dir: str = "uploads/videos"
    annotated_export_dir: str = "uploads/annotated_exports"
    asset_upload_dir: str = "uploads/assets"
    music_asset_dir: str = "uploads/assets/music"
    branding_asset_dir: str = "uploads/assets/branding"
    player_photo_asset_dir: str = "uploads/assets/players"
    allowed_video_extensions: str = ".mp4,.mov,.avi,.mkv"

    # --- Milestone 5: highlight clip extraction & stitching ---------------
    # Where rendered highlight reels and their per-event clips are written.
    highlight_export_dir: str = "uploads/highlights"
    # Seconds of context added before/after each derived event window.
    highlight_pad_pre_sec: float = 2.0
    highlight_pad_post_sec: float = 2.0
    # Upper bound on clips per reel (after ranking) to keep reels watchable.
    highlight_max_clips: int = 20
    # A shot/layup is flagged "made" if a ball-in-basket detection lands within
    # this many seconds after the event ends.
    highlight_made_shot_window_sec: float = 1.5

    # --- Milestone 6: professional personalized reel composition -----------
    # Where composed (polished) reels are rendered before/while serving.
    compose_export_dir: str = "uploads/composed"
    # Local temp workspace for assets pulled from R2 + intermediate renders.
    compose_work_dir: str = "uploads/compose_work"
    # R2 prefixes the brand/music assets live under (see asset upload routes).
    compose_music_prefix: str = "assets/music/"
    compose_branding_prefix: str = "assets/branding/"
    # Font used for intro card + overlays. fonts-dejavu-core is installed in the
    # Docker image; this path resolves there. Pillow falls back to a default if
    # the file is missing so local non-Docker runs still work.
    compose_font_path: str = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    compose_font_bold_path: str = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    # Intro/title card duration (seconds) prepended to the reel.
    compose_intro_duration_sec: float = 3.0
    # Fade duration (seconds) applied to the start/end of every segment for pacing.
    compose_transition_sec: float = 0.5
    # Music bed level and the level the original game audio is ducked to.
    compose_music_volume: float = 0.35
    compose_duck_level: float = 0.25
    # Brand watermark opacity (0-1) for the persistent corner logo.
    compose_watermark_opacity: float = 0.75
    # Default output aspect. "16:9" (landscape) or "9:16" (vertical social).
    compose_default_aspect: str = "16:9"
    # Encode size for the 16:9 profile (vertical uses the swapped dimensions).
    # 1080 (Full HD) for a crisp, deployment-ready master.
    compose_video_height: int = 1080

    # --- Milestone 4: Modal orchestration ---------------------------------
    # When enabled, /upload mirrors the saved video to Cloudflare R2 and spawns
    # the deployed Modal job to process it on GPU. When disabled (default), the
    # endpoint behaves exactly as before (local save only), so existing flows
    # and tests keep working without any cloud credentials.
    enable_modal_orchestration: bool = False

    # Deployed Modal app + class to spawn (see modal_app/cv_app.py).
    modal_app_name: str = "hoopstar-cv"
    modal_cls_name: str = "BasketballModels"

    # Temporal subsampling: process every Nth source frame on the GPU worker.
    # Stride 3 over a 30fps clip ≈ 10 effective fps — the biggest throughput
    # lever. Reported frame numbers/timestamps stay mapped to real source frames,
    # so downstream timing is unaffected. Set 1 to process every frame.
    cv_frame_stride: int = 3

    # Chunked parallel processing: split a video into this many time-segments
    # and process each on its own Modal GPU worker simultaneously. Wall-clock
    # time drops roughly proportionally to chunk_count. Default 6 gives ~5-min
    # segments for a 30-min game on A10G, targeting <=20 min wall-clock.
    # Set 1 to use the legacy single-worker path (useful for short test clips).
    cv_chunk_count: int = 6

    # Public base URL FastAPI is reachable at FROM Modal (e.g. an ngrok tunnel in
    # dev, or the real domain in prod). Modal POSTs detection batches to
    # ``{webhook_base_url}/api/videos/{job_id}/colab-detections``.
    webhook_base_url: str = "http://localhost:8000"

    # Shared HMAC-SHA256 secret. The SAME value must live in the Modal secret so
    # the worker can sign callbacks and this API can verify them. Empty string
    # disables verification (dev convenience only — set it in any real deploy).
    webhook_hmac_secret: str = ""

    # Cloudflare R2 (S3-compatible). Credentials are read from the environment.
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = ""
    # Optional explicit endpoint; if blank it is derived from the account id.
    r2_endpoint_url: str = ""
    # How long (seconds) the presigned download URL handed to Modal stays valid.
    r2_presign_expiry_sec: int = 3600

    @property
    def resolved_r2_endpoint_url(self) -> str:
        if self.r2_endpoint_url:
            return self.r2_endpoint_url
        if self.r2_account_id:
            return f"https://{self.r2_account_id}.r2.cloudflarestorage.com"
        return ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()

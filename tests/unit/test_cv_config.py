from app.core.config import settings
from app.cv.storage import parse_allowed_extensions


def test_cv_settings_defaults_are_present() -> None:
    assert settings.cv_model_path
    assert 0.0 < settings.cv_confidence_threshold <= 1.0
    assert settings.cv_min_player_height_px > 0
    assert settings.cv_target_fps > 0
    assert settings.max_upload_size_mb > 0


def test_allowed_video_extensions_parse() -> None:
    parsed_extensions = parse_allowed_extensions(settings.allowed_video_extensions)
    assert ".mp4" in parsed_extensions
    assert all(extension.startswith(".") for extension in parsed_extensions)

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


def test_remediation_flags_default_to_current_behavior() -> None:
    """Every remediation flag must default to the pre-fix behavior so the
    pipeline is unchanged until a flag is explicitly flipped."""
    assert settings.dedup_by_player is False
    assert settings.dedup_cross_type_suppression is False
    assert settings.track_consolidation is False
    assert settings.action_temporal_voting is False
    assert settings.opponent_team_gate is False
    assert settings.overlap_resolution is False
    # 0 means "off" for the interval-style flag.
    assert settings.periodic_redetect_interval == 0

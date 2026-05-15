from app.cv.annotated_export import format_ocr_label, format_player_label
from app.db.models import Player


def test_format_player_label_prefers_mapped_player() -> None:
    player = Player(id=1, team_id=9, jersey_number=1, full_name="Einav Hillel")

    result = format_player_label(player, detected_jersey=23)

    assert result == "Einav Hillel #1"


def test_format_player_label_falls_back_to_detected_jersey() -> None:
    result = format_player_label(None, detected_jersey=23)

    assert result == "Unknown #23"


def test_format_ocr_label_handles_missing_jersey() -> None:
    assert format_ocr_label(None) == "OCR --"
    assert format_ocr_label(23) == "OCR #23"
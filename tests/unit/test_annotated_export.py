from app.cv.annotated_export import (
    format_ocr_label,
    format_player_label,
    select_single_box_per_player,
)
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


def test_select_single_box_per_player_keeps_largest_box() -> None:
    player = Player(id=40, team_id=1, jersey_number=10, full_name="Colton Large")
    # Tracks 5 and 12 are the SAME player; track 5's box is larger.
    track_boxes = {
        5: (0, 0, 100, 200),   # area 20000
        12: (0, 0, 50, 100),   # area 5000 — fragment, should be suppressed
    }
    identity = {5: (player, 10), 12: (player, 10)}

    selected = select_single_box_per_player(track_boxes, identity)

    assert set(selected) == {5}


def test_select_single_box_per_player_keeps_distinct_players_and_unmapped() -> None:
    p40 = Player(id=40, team_id=1, jersey_number=10, full_name="Colton Large")
    p41 = Player(id=41, team_id=1, jersey_number=11, full_name="Owen Nunemaker")
    track_boxes = {
        5: (0, 0, 100, 200),
        7: (0, 0, 80, 160),
        99: (0, 0, 60, 120),  # unmapped opponent/unknown — always kept
    }
    identity = {5: (p40, 10), 7: (p41, 11), 99: (None, None)}

    selected = select_single_box_per_player(track_boxes, identity)

    assert set(selected) == {5, 7, 99}
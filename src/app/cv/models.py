"""Model constants, loaders and basketball reference data for the CV pipeline.

This module is the de-duplicated home for everything the Colab notebook hard
coded inline: the Roboflow model IDs, inference thresholds, the RF-DETR class
map, and the team rosters / colors used to turn jersey numbers into names.

The heavy model objects themselves are loaded once per Modal container in
``modal_app/cv_app.py`` via ``@modal.enter()``. The thin loader helpers here
exist so the same load logic can be reused from tests or a future local run
without copy-pasting ``get_model(...)`` calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# --- Roboflow model IDs ------------------------------------------------------

PLAYER_DETECTION_MODEL_ID = "basketball-player-detection-3-ycjdo/4"
NUMBER_RECOGNITION_MODEL_ID = "basketball-jersey-numbers-ocr/3"
NUMBER_RECOGNITION_MODEL_PROMPT = "Read the number."

# --- Inference thresholds (match the Colab values) ---------------------------

PLAYER_DETECTION_MODEL_CONFIDENCE = 0.4
PLAYER_DETECTION_MODEL_IOU_THRESHOLD = 0.9

# --- RF-DETR class map -------------------------------------------------------

CLASS_ID_TO_NAME: dict[int, str] = {
    0: "ball",
    1: "ball-in-basket",
    2: "number",
    3: "player",
    4: "player-in-possession",
    5: "player-jump-shot",
    6: "player-layup-dunk",
    7: "player-shot-block",
    8: "referee",
    9: "rim",
}

# Player-ish classes used to seed SAM-2 tracks. The non-default values double as
# action labels (in-possession / jump-shot / layup-dunk / shot-block).
PLAYER_CLASS_IDS: list[int] = [3, 4, 5, 6, 7]
NUMBER_CLASS_ID = 2

# --- Team reference data -----------------------------------------------------

# Default team-id -> team-name mapping for the sample Knicks/Celtics clip. For a
# generic clip the names are arbitrary; roster lookups simply return None.
TEAM_NAMES: dict[int, str] = {
    0: "Boston Celtics",
    1: "New York Knicks",
}

TEAM_COLORS: dict[str, str] = {
    "New York Knicks": "#006BB6",
    "Boston Celtics": "#007A33",
}

TEAM_ROSTERS: dict[str, dict[str, str]] = {
    "New York Knicks": {
        "55": "Hukporti",
        "1": "Payne",
        "0": "Wright",
        "11": "Brunson",
        "3": "Hart",
        "32": "Towns",
        "44": "Shamet",
        "25": "Bridges",
        "2": "McBride",
        "23": "Robinson",
        "8": "Anunoby",
        "4": "Dadiet",
        "5": "Achiuwa",
        "13": "Kolek",
    },
    "Boston Celtics": {
        "42": "Horford",
        "55": "Scheierman",
        "9": "White",
        "20": "Davison",
        "7": "Brown",
        "0": "Tatum",
        "27": "Walsh",
        "4": "Holiday",
        "8": "Porzingis",
        "40": "Kornet",
        "88": "Queta",
        "11": "Pritchard",
        "30": "Hauser",
        "12": "Craig",
        "26": "Tillman",
    },
}


def roster_name(team_name: str | None, jersey_number: str | None) -> str | None:
    """Resolve a jersey number to a player name via ``TEAM_ROSTERS``."""
    if not team_name or jersey_number is None:
        return None
    return TEAM_ROSTERS.get(team_name, {}).get(str(jersey_number))


# --- Model loaders -----------------------------------------------------------


@dataclass
class LoadedModels:
    """Bundle of the four warm model objects the pipeline needs."""

    detector: Any
    ocr: Any
    predictor: Any
    team_classifier: Any


def load_detector() -> Any:
    """Load the RF-DETR player/number/action detection model."""
    from inference import get_model

    return get_model(model_id=PLAYER_DETECTION_MODEL_ID)


def load_ocr() -> Any:
    """Load the SmolVLM2 jersey-number OCR model."""
    from inference import get_model

    return get_model(model_id=NUMBER_RECOGNITION_MODEL_ID)


def load_team_classifier() -> Any:
    """Create the SigLIP-based team classifier (must be ``.fit`` per video)."""
    from sports import TeamClassifier

    return TeamClassifier(device="cuda")

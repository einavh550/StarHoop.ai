import argparse
import json
import sys
from typing import Any

import requests


def build_payload() -> dict[str, Any]:
    return {
        "batch_id": "test-batch-001",
        "source": "colab",
        "final_batch": False,
        "frames": [
            {
                "frame_number": 120,
                "timestamp_sec": 4.0,
                "detections": [
                    {
                        "track_id": 7,
                        "bbox": {"x1": 100.0, "y1": 120.5, "x2": 240.2, "y2": 380.9},
                        "class_id": 3,
                        "class_name": "player",
                        "confidence": 0.92,
                        "team_id": 0,
                        "team_name": "Boston Celtics",
                        "jersey_number": 0,
                        "jersey_confidence": 0.87,
                        "player_id": None,
                        "player_name": "Jayson Tatum",
                    }
                ],
            },
            {
                "frame_number": 121,
                "timestamp_sec": 4.04,
                "detections": [
                    {
                        "track_id": 7,
                        "bbox": {"x1": 102.0, "y1": 121.0, "x2": 241.0, "y2": 381.2},
                        "class_id": 3,
                        "class_name": "player",
                        "confidence": 0.91,
                        "team_id": 0,
                        "team_name": "Boston Celtics",
                        "jersey_number": 0,
                        "jersey_confidence": 0.88,
                        "player_id": None,
                        "player_name": "Jayson Tatum",
                    }
                ],
            },
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a fake Colab batch to the FastAPI ingestion endpoint.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="FastAPI base URL")
    parser.add_argument("--job-id", type=int, default=12, help="Video job id")
    parser.add_argument("--final", action="store_true", help="Mark payload as final batch")
    args = parser.parse_args()

    payload = build_payload()
    payload["final_batch"] = bool(args.final)

    url = f"{args.base_url.rstrip('/')}/api/videos/{args.job_id}/colab-detections"
    try:
        response = requests.post(url, json=payload, timeout=20)
    except requests.RequestException as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        return 1

    print(f"Status: {response.status_code}")
    try:
        print(json.dumps(response.json(), indent=2))
    except ValueError:
        print(response.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

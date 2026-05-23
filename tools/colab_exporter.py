"""Colab-side exporter for sending real detections to the FastAPI ingestion endpoint.

Usage (Colab):
    from tools.colab_exporter import ColabIngestClient, ColabBatchBuffer, build_frame_payload

    client = ColabIngestClient(base_url=NGROK_URL, job_id=JOB_ID)
    buffer = ColabBatchBuffer(client, max_frames=120, max_bytes=900_000)

    # For each frame: build detections list, then add
    frame_payload = build_frame_payload(frame_number, timestamp_sec, detections)
    buffer.add_frame(frame_payload)

    # At end of video
    buffer.flush(final_batch=True)
"""

from __future__ import annotations

import json
import math
import time
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


@dataclass(frozen=True)
class ExporterConfig:
    max_frames: int = 120
    max_bytes: int = 900_000
    source: str = "colab"
    timeout_sec: float = 20.0
    max_retries: int = 5
    backoff_sec: float = 0.5
    verify_ssl: bool = True


def _is_finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def _coerce_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _coerce_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    if isinstance(value, str):
        try:
            parsed = float(value.strip())
        except ValueError:
            return None
        return parsed if math.isfinite(parsed) else None
    return None


def _clamp_01(value: float | None) -> float:
    if value is None or not math.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, float(value)))


def _validate_bbox(x1: Any, y1: Any, x2: Any, y2: Any) -> tuple[float, float, float, float] | None:
    if not all(_is_finite(v) for v in (x1, y1, x2, y2)):
        return None
    x1_f, y1_f, x2_f, y2_f = float(x1), float(y1), float(x2), float(y2)
    if x2_f < x1_f or y2_f < y1_f:
        return None
    return x1_f, y1_f, x2_f, y2_f


def build_detection(
    *,
    track_id: int,
    bbox_xyxy: Sequence[float],
    class_id: int | None = None,
    class_name: str | None = None,
    confidence: float | None = None,
    team_id: int | None = None,
    team_name: str | None = None,
    jersey_number: int | str | None = None,
    jersey_confidence: float | None = None,
    player_id: int | None = None,
    player_name: str | None = None,
) -> dict[str, Any] | None:
    if track_id is None:
        return None
    if len(bbox_xyxy) != 4:
        return None

    bbox = _validate_bbox(bbox_xyxy[0], bbox_xyxy[1], bbox_xyxy[2], bbox_xyxy[3])
    if bbox is None:
        return None

    detection = {
        "track_id": int(track_id),
        "bbox": {"x1": bbox[0], "y1": bbox[1], "x2": bbox[2], "y2": bbox[3]},
        "class_id": _coerce_optional_int(class_id),
        "class_name": class_name,
        "confidence": _coerce_optional_float(confidence),
        "team_id": _coerce_optional_int(team_id),
        "team_name": team_name,
        "jersey_number": _coerce_optional_int(jersey_number),
        "jersey_confidence": _clamp_01(_coerce_optional_float(jersey_confidence)),
        "player_id": _coerce_optional_int(player_id),
        "player_name": player_name,
    }

    return detection


def build_frame_payload(
    frame_number: int,
    timestamp_sec: float,
    detections: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    if frame_number < 0:
        raise ValueError("frame_number must be non-negative")
    if not _is_finite(timestamp_sec):
        raise ValueError("timestamp_sec must be finite")

    payload_detections = [dict(det) for det in detections]
    return {
        "frame_number": int(frame_number),
        "timestamp_sec": float(timestamp_sec),
        "detections": payload_detections,
    }


def detections_from_supervision(
    detections: Any,
    *,
    class_id: int | None = None,
    class_name: str | None = None,
    confidence: Sequence[float] | None = None,
    team_ids: Sequence[int] | None = None,
    team_names: Mapping[int, str] | None = None,
    jersey_numbers: Sequence[Any] | None = None,
    jersey_confidences: Sequence[float] | None = None,
    player_ids: Sequence[int] | None = None,
    player_names: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    xyxy = getattr(detections, "xyxy", None)
    track_ids = getattr(detections, "tracker_id", None)
    if xyxy is None or track_ids is None:
        raise ValueError("detections must expose xyxy and tracker_id")

    output: list[dict[str, Any]] = []
    count = len(xyxy)

    for idx in range(count):
        track_id = track_ids[idx]
        if track_id is None:
            continue

        team_id = team_ids[idx] if team_ids is not None and idx < len(team_ids) else None
        team_name = team_names.get(int(team_id)) if team_names and team_id is not None else None
        jersey_number = jersey_numbers[idx] if jersey_numbers is not None and idx < len(jersey_numbers) else None
        jersey_confidence = (
            jersey_confidences[idx]
            if jersey_confidences is not None and idx < len(jersey_confidences)
            else None
        )
        player_id = player_ids[idx] if player_ids is not None and idx < len(player_ids) else None
        player_name = player_names[idx] if player_names is not None and idx < len(player_names) else None
        conf = confidence[idx] if confidence is not None and idx < len(confidence) else None

        detection = build_detection(
            track_id=int(track_id),
            bbox_xyxy=xyxy[idx],
            class_id=class_id,
            class_name=class_name,
            confidence=conf,
            team_id=team_id,
            team_name=team_name,
            jersey_number=jersey_number,
            jersey_confidence=jersey_confidence,
            player_id=player_id,
            player_name=player_name,
        )
        if detection:
            output.append(detection)

    return output


class ColabIngestClient:
    def __init__(self, base_url: str, job_id: int, config: ExporterConfig | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.job_id = int(job_id)
        self.config = config or ExporterConfig()
        self._session = requests.Session()

        retry = Retry(
            total=self.config.max_retries,
            connect=self.config.max_retries,
            read=self.config.max_retries,
            status=self.config.max_retries,
            backoff_factor=self.config.backoff_sec,
            status_forcelist=(408, 425, 429, 500, 502, 503, 504),
            allowed_methods=("POST",),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

    @property
    def ingest_url(self) -> str:
        return f"{self.base_url}/api/videos/{self.job_id}/colab-detections"

    def send_batch(
        self,
        frames: Sequence[Mapping[str, Any]],
        *,
        final_batch: bool = False,
        batch_id: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "batch_id": batch_id or self._make_batch_id(frames),
            "source": self.config.source,
            "final_batch": bool(final_batch),
            "frames": list(frames),
        }

        response = self._session.post(
            self.ingest_url,
            json=payload,
            timeout=self.config.timeout_sec,
            verify=self.config.verify_ssl,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Ingest failed {response.status_code}: {response.text}")

        try:
            return response.json()
        except ValueError:
            return {"status_code": response.status_code, "text": response.text}

    def _make_batch_id(self, frames: Sequence[Mapping[str, Any]]) -> str:
        if not frames:
            return f"job-{self.job_id}-empty-{uuid.uuid4().hex[:8]}"
        start = frames[0].get("frame_number")
        end = frames[-1].get("frame_number")
        return f"job-{self.job_id}-{start}-{end}-{uuid.uuid4().hex[:8]}"


class ColabBatchBuffer:
    def __init__(self, client: ColabIngestClient, max_frames: int | None = None, max_bytes: int | None = None):
        self.client = client
        self.max_frames = max_frames or client.config.max_frames
        self.max_bytes = max_bytes or client.config.max_bytes
        self._frames: list[dict[str, Any]] = []
        self._byte_size = 0

    def add_frame(self, frame_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        self._frames.append(dict(frame_payload))
        self._byte_size = self._estimate_payload_size(self._frames)

        if len(self._frames) >= self.max_frames or self._byte_size >= self.max_bytes:
            return self.flush(final_batch=False)

        return []

    def flush(self, final_batch: bool) -> list[dict[str, Any]]:
        if not self._frames:
            if final_batch:
                return [self.client.send_batch([], final_batch=True)]
            return []

        frames = self._frames
        self._frames = []
        self._byte_size = 0

        response = self.client.send_batch(frames, final_batch=final_batch)
        return [response]

    @staticmethod
    def _estimate_payload_size(frames: Sequence[Mapping[str, Any]]) -> int:
        payload = {
            "batch_id": "size-estimate",
            "source": "colab",
            "final_batch": False,
            "frames": list(frames),
        }
        return len(json.dumps(payload, separators=(",", ":")).encode("utf-8"))


def wait_between_batches(seconds: float = 0.0) -> None:
    if seconds > 0:
        time.sleep(seconds)

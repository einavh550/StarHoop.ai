"""Trigger the deployed Modal CV job from FastAPI (Milestone 4 / SLA sprint).

Two execution paths:

* **Chunked (default)**: ``spawn_chunked_processing`` splits the video into K
  time-segments and fans out K Modal workers simultaneously. Wall-clock time
  drops proportionally to K (configured via ``cv_chunk_count``). Each chunk
  worker offsets its SAM-2 track IDs by ``chunk_index * TRACK_ID_BLOCK`` so
  detection rows never collide in the DB.

* **Legacy single-worker**: ``spawn_processing`` retained for short test clips
  or when ``cv_chunk_count == 1``.

``modal`` is imported lazily so importing this module never requires Modal
credentials; only an actual spawn does.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.config import settings

# Each chunk owns a block of 10 000 track IDs, large enough for any realistic
# number of tracked objects per segment.
TRACK_ID_BLOCK = 10_000
logger = logging.getLogger(__name__)


class OrchestrationError(RuntimeError):
    """Raised when the Modal job cannot be spawned or cancelled."""


@dataclass
class ChunkSpec:
    """Immutable description of one time-segment chunk."""

    chunk_index: int
    start_frame: int
    end_frame: int  # exclusive upper bound passed to supervision generator
    track_id_offset: int


def build_callback_url(job_id: int) -> str:
    """The webhook URL Modal POSTs detection batches to for ``job_id``."""
    base = settings.webhook_base_url.rstrip("/")
    return f"{base}/api/videos/{job_id}/colab-detections"


def build_status_url(job_id: int) -> str:
    base = settings.webhook_base_url.rstrip("/")
    return f"{base}/api/videos/{job_id}/status"


def build_total_frames_url(job_id: int) -> str:
    base = settings.webhook_base_url.rstrip("/")
    return f"{base}/api/videos/{job_id}/total-frames"


def _compute_chunks(total_frames: int, chunk_count: int) -> list[ChunkSpec]:
    """Divide ``total_frames`` into ``chunk_count`` roughly-equal segments."""
    chunk_count = max(1, chunk_count)
    size = max(1, total_frames // chunk_count)
    specs: list[ChunkSpec] = []
    for i in range(chunk_count):
        start = i * size
        # Last chunk takes any remainder so we never miss frames.
        end = total_frames if i == chunk_count - 1 else start + size
        specs.append(
            ChunkSpec(
                chunk_index=i,
                start_frame=start,
                end_frame=end,
                track_id_offset=i * TRACK_ID_BLOCK,
            )
        )
    return specs


def spawn_chunked_processing(
    job_id: int,
    video_url: str,
    total_frames: int,
) -> list[tuple[ChunkSpec, str]]:
    """Fan out K Modal workers, one per chunk. Returns ``[(ChunkSpec, call_id)]``.

    Raises :class:`OrchestrationError` if any spawn fails.  On partial failure
    the caller is responsible for cleaning up already-spawned calls.
    """
    import modal

    chunk_count = settings.cv_chunk_count
    if chunk_count <= 1 or total_frames <= 0:
        # Fall back to single-worker path.
        call_id = spawn_processing(job_id, video_url)
        single = ChunkSpec(
            chunk_index=0,
            start_frame=0,
            end_frame=total_frames or 0,
            track_id_offset=0,
        )
        return [(single, call_id)]

    chunks = _compute_chunks(total_frames, chunk_count)
    callback_url = build_callback_url(job_id)
    status_url = build_status_url(job_id)

    try:
        model_cls = modal.Cls.from_name(settings.modal_app_name, settings.modal_cls_name)
        results: list[tuple[ChunkSpec, str]] = []
        for spec in chunks:
            handle = model_cls().process_chunk.spawn(
                video_url=video_url,
                job_id=job_id,
                chunk_index=spec.chunk_index,
                start_frame=spec.start_frame,
                end_frame=spec.end_frame,
                track_id_offset=spec.track_id_offset,
                callback_url=callback_url,
                status_url=status_url,
                hmac_secret=settings.webhook_hmac_secret,
                frame_stride=settings.cv_frame_stride,
            )
            results.append((spec, handle.object_id))
        return results
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Failed to spawn chunked Modal job for job_id=%s",
            job_id,
        )
        raise OrchestrationError(
            f"Failed to spawn chunked Modal job for job_id={job_id}: {exc}"
        ) from exc


def spawn_processing(job_id: int, video_url: str) -> str:
    """Spawn a single Modal worker (legacy / short-clip path). Returns call id."""
    import modal

    try:
        model_cls = modal.Cls.from_name(settings.modal_app_name, settings.modal_cls_name)
        handle = model_cls().process_and_callback.spawn(
            video_url=video_url,
            job_id=job_id,
            callback_url=build_callback_url(job_id),
            hmac_secret=settings.webhook_hmac_secret,
            frame_stride=settings.cv_frame_stride,
        )
        return handle.object_id
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Failed to spawn Modal job %s.%s for job_id=%s",
            settings.modal_app_name,
            settings.modal_cls_name,
            job_id,
        )
        raise OrchestrationError(
            f"Failed to spawn Modal job '{settings.modal_app_name}.{settings.modal_cls_name}': {exc}"
        ) from exc


def cancel_processing(call_id: str) -> None:
    """Cancel a single Modal call by id."""
    import modal

    try:
        modal.FunctionCall.from_id(call_id).cancel()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to cancel Modal call %s", call_id)
        raise OrchestrationError(f"Failed to cancel Modal call '{call_id}': {exc}") from exc


def cancel_all_chunks(call_ids: list[str]) -> list[str]:
    """Best-effort cancel of multiple chunk call IDs. Returns list of failed ids."""
    failed: list[str] = []
    for call_id in call_ids:
        try:
            cancel_processing(call_id)
        except OrchestrationError:
            failed.append(call_id)
    return failed

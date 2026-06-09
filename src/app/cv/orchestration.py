"""Trigger the deployed Modal CV job from FastAPI (Milestone 4).

``/upload`` calls :func:`spawn_processing` after the video is in R2. We look up
the *deployed* Modal class by name and ``.spawn()`` its ``process_and_callback``
method, which returns immediately with a call id while the GPU work runs
asynchronously. The worker streams results back to our webhook.

``modal`` is imported lazily so importing this module never requires Modal
credentials; only an actual spawn does.
"""

from __future__ import annotations

from app.core.config import settings


class OrchestrationError(RuntimeError):
    """Raised when the Modal job cannot be spawned."""


def build_callback_url(job_id: int) -> str:
    """The webhook URL Modal POSTs detection batches to for ``job_id``."""
    base = settings.webhook_base_url.rstrip("/")
    return f"{base}/api/videos/{job_id}/colab-detections"


def spawn_processing(job_id: int, video_url: str) -> str:
    """Spawn the deployed Modal job. Returns the Modal call id.

    Raises :class:`OrchestrationError` if Modal is unreachable or not deployed,
    so the caller can mark the job failed instead of leaving it stuck.
    """
    import modal

    try:
        model_cls = modal.Cls.from_name(settings.modal_app_name, settings.modal_cls_name)
        handle = model_cls().process_and_callback.spawn(
            video_url=video_url,
            job_id=job_id,
            callback_url=build_callback_url(job_id),
            hmac_secret=settings.webhook_hmac_secret,
        )
        return handle.object_id
    except Exception as exc:  # noqa: BLE001 - surface any Modal failure uniformly
        raise OrchestrationError(
            f"Failed to spawn Modal job '{settings.modal_app_name}.{settings.modal_cls_name}': {exc}"
        ) from exc


def cancel_processing(call_id: str) -> None:
    """Cancel a running Modal call by id.

    Raises :class:`OrchestrationError` if the cancellation request cannot be
    issued. The caller decides how to surface this to users.
    """
    import modal

    try:
        modal.FunctionCall.from_id(call_id).cancel()
    except Exception as exc:  # noqa: BLE001 - normalize all Modal failures
        raise OrchestrationError(f"Failed to cancel Modal call '{call_id}': {exc}") from exc

"""Cloudflare R2 object storage client (Milestone 4).

R2 speaks the S3 API, so we drive it with ``boto3``'s S3 client pointed at the
R2 endpoint. ``/upload`` mirrors the saved video here and hands Modal a short
lived presigned GET URL so the GPU worker can stream the file without ever
holding our credentials.

``boto3`` is imported lazily so the dependency is only required when
orchestration is actually enabled.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.core.config import settings


class R2ConfigurationError(RuntimeError):
    """Raised when R2 is used before its credentials are configured."""


@lru_cache(maxsize=1)
def _client():
    endpoint = settings.resolved_r2_endpoint_url
    missing = [
        name
        for name, value in (
            ("R2_ACCESS_KEY_ID", settings.r2_access_key_id),
            ("R2_SECRET_ACCESS_KEY", settings.r2_secret_access_key),
            ("R2_BUCKET", settings.r2_bucket),
            ("R2_ACCOUNT_ID or R2_ENDPOINT_URL", endpoint),
        )
        if not value
    ]
    if missing:
        raise R2ConfigurationError(
            "R2 storage is enabled but not configured. Missing: " + ", ".join(missing)
        )

    import boto3  # local import: only needed when orchestration is enabled
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        # R2 ignores the region but boto3 requires one; "auto" is the convention.
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def upload_video(local_path: str, key: str) -> str:
    """Upload ``local_path`` to the R2 bucket under ``key`` and return the key."""
    client = _client()
    content_type = _guess_content_type(local_path)
    client.upload_file(
        Filename=local_path,
        Bucket=settings.r2_bucket,
        Key=key,
        ExtraArgs={"ContentType": content_type},
    )
    return key


def generate_presigned_get_url(key: str, expires_in: int | None = None) -> str:
    """Return a time-limited URL Modal can use to download the object."""
    client = _client()
    return client.generate_presigned_url(
        ClientMethod="get_object",
        Params={"Bucket": settings.r2_bucket, "Key": key},
        ExpiresIn=expires_in or settings.r2_presign_expiry_sec,
    )


def _guess_content_type(local_path: str) -> str:
    suffix = Path(local_path).suffix.lower()
    return {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".avi": "video/x-msvideo",
        ".mkv": "video/x-matroska",
    }.get(suffix, "application/octet-stream")

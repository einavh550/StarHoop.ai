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
from mimetypes import guess_type
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


def upload_file(local_path: str, key: str, content_type: str | None = None) -> str:
    """Upload ``local_path`` to the R2 bucket under ``key`` and return the key."""
    client = _client()
    resolved_content_type = content_type or _guess_content_type(local_path)
    client.upload_file(
        Filename=local_path,
        Bucket=settings.r2_bucket,
        Key=key,
        ExtraArgs={"ContentType": resolved_content_type},
    )
    return key


def upload_video(local_path: str, key: str) -> str:
    return upload_file(local_path=local_path, key=key)


def generate_presigned_get_url(key: str, expires_in: int | None = None) -> str:
    """Return a time-limited URL Modal can use to download the object."""
    client = _client()
    return client.generate_presigned_url(
        ClientMethod="get_object",
        Params={"Bucket": settings.r2_bucket, "Key": key},
        ExpiresIn=expires_in or settings.r2_presign_expiry_sec,
    )


def download_file(key: str, local_path: str | Path) -> str:
    """Download the object stored under ``key`` to ``local_path``.

    The parent directory is created if needed. Returns the local path as a string.
    """
    client = _client()
    destination = Path(local_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    client.download_file(Bucket=settings.r2_bucket, Key=key, Filename=str(destination))
    return str(destination)


def list_keys(prefix: str) -> list[str]:
    """Return every object key under ``prefix`` (handles pagination)."""
    client = _client()
    keys: list[str] = []
    continuation_token: str | None = None
    while True:
        kwargs = {"Bucket": settings.r2_bucket, "Prefix": prefix}
        if continuation_token:
            kwargs["ContinuationToken"] = continuation_token
        response = client.list_objects_v2(**kwargs)
        for obj in response.get("Contents", []):
            key = obj["Key"]
            if not key.endswith("/"):
                keys.append(key)
        if response.get("IsTruncated"):
            continuation_token = response.get("NextContinuationToken")
        else:
            break
    return sorted(keys)


def _guess_content_type(local_path: str) -> str:
    suffix = Path(local_path).suffix.lower()
    return {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".avi": "video/x-msvideo",
        ".mkv": "video/x-matroska",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(suffix, "application/octet-stream")

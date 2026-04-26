import re
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile


def parse_allowed_extensions(raw_extensions: str) -> set[str]:
    normalized_extensions: set[str] = set()
    for raw_extension in raw_extensions.split(","):
        cleaned = raw_extension.strip().lower()
        if not cleaned:
            continue
        if not cleaned.startswith("."):
            cleaned = f".{cleaned}"
        normalized_extensions.add(cleaned)
    return normalized_extensions


def ensure_storage_directory(storage_dir: str) -> Path:
    path = Path(storage_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_filename_stem(filename: str) -> str:
    stem = Path(filename).stem
    safe_stem = re.sub(r"[^A-Za-z0-9._-]", "_", stem)
    return safe_stem or "video"


def build_storage_path(filename: str, storage_dir: Path) -> Path:
    suffix = Path(filename).suffix.lower()
    safe_stem = _safe_filename_stem(filename)
    return storage_dir / f"{uuid4().hex}_{safe_stem}{suffix}"


async def save_upload_file(
    upload_file: UploadFile,
    storage_dir: str,
    max_size_mb: int,
    allowed_extensions: set[str],
) -> tuple[str, str]:
    if not upload_file.filename:
        raise ValueError("Uploaded file must have a filename.")

    extension = Path(upload_file.filename).suffix.lower()
    if extension not in allowed_extensions:
        allowed_values = ", ".join(sorted(allowed_extensions))
        raise ValueError(f"Unsupported file extension '{extension}'. Allowed: {allowed_values}.")

    output_dir = ensure_storage_directory(storage_dir)
    output_path = build_storage_path(upload_file.filename, output_dir)
    max_size_bytes = max_size_mb * 1024 * 1024
    current_size = 0

    try:
        with output_path.open("wb") as destination:
            while True:
                chunk = await upload_file.read(1024 * 1024)
                if not chunk:
                    break
                current_size += len(chunk)
                if current_size > max_size_bytes:
                    raise ValueError(f"Upload exceeds max size of {max_size_mb} MB.")
                destination.write(chunk)
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    finally:
        await upload_file.close()

    return upload_file.filename, str(output_path.resolve())

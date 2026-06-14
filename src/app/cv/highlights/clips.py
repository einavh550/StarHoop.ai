"""Clip extraction and stitching for the highlight pipeline.

* :func:`resolve_source` picks the video the clips are cut from -- either the
  clean original (``job.storage_path``) or the most recent annotated export.
* :func:`extract_clip` cuts a single padded, frame-accurate sub-clip, clamped to
  the source duration, re-encoded to a uniform codec so the clips can be
  concatenated cleanly.
* :func:`stitch_clips` concatenates the extracted clips into one reel MP4 using
  the ffmpeg concat demuxer.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.cv.highlights.ffmpeg import probe_duration, run_ffmpeg
from app.db.models import VideoJob

logger = logging.getLogger(__name__)

SOURCE_CLEAN = "clean"
SOURCE_ANNOTATED = "annotated"
VALID_SOURCE_MODES: frozenset[str] = frozenset({SOURCE_CLEAN, SOURCE_ANNOTATED})

# Uniform encode settings so every clip shares codec params -> concat-copy works.
_VIDEO_ARGS = ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p"]
_AUDIO_ARGS = ["-c:a", "aac", "-b:a", "128k"]


class ClipExtractionError(RuntimeError):
    """Raised when a source cannot be resolved or a clip/stitch step fails."""


def resolve_source(db: Session, job: VideoJob, source_mode: str) -> Path:
    """Return the video file path for ``source_mode``.

    Raises:
        ClipExtractionError: If the mode is unknown, the file is missing, or no
            annotated export exists yet for the annotated mode.
    """
    if source_mode not in VALID_SOURCE_MODES:
        raise ClipExtractionError(
            f"Unknown source mode '{source_mode}'. Expected one of: {sorted(VALID_SOURCE_MODES)}"
        )

    if source_mode == SOURCE_CLEAN:
        path = Path(job.storage_path)
        if not path.exists():
            raise ClipExtractionError(f"Source video not found at {path}")
        return path

    annotated = _latest_annotated_export(job.id)
    if annotated is None:
        raise ClipExtractionError(
            f"No annotated export found for job {job.id}; create one before requesting source=annotated"
        )
    return annotated


def _latest_annotated_export(job_id: int) -> Path | None:
    export_root = Path(settings.annotated_export_dir) / f"job_{job_id}"
    if not export_root.is_dir():
        return None
    candidates = [p for p in export_root.glob("*.mp4") if p.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def extract_clip(
    source_path: str | Path,
    *,
    start_sec: float,
    end_sec: float,
    pad_pre_sec: float,
    pad_post_sec: float,
    output_path: str | Path,
    source_duration_sec: float | None = None,
) -> float:
    """Extract a padded sub-clip from ``source_path`` to ``output_path``.

    The window is padded and clamped to ``[0, duration]``. Input seeking plus a
    re-encode yields a frame-accurate, uniformly encoded clip.

    Returns:
        The actual clip duration in seconds.

    Raises:
        ClipExtractionError: If the requested window is empty after clamping.
        FFmpegError: If the ffmpeg invocation fails.
    """
    duration = source_duration_sec if source_duration_sec is not None else probe_duration(source_path)

    clip_start = max(0.0, start_sec - pad_pre_sec)
    clip_end = min(duration, end_sec + pad_post_sec)
    clip_duration = clip_end - clip_start
    if clip_duration <= 0:
        raise ClipExtractionError(
            f"Empty clip window after clamping (start={clip_start:.3f}, end={clip_end:.3f}, "
            f"duration={duration:.3f})"
        )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    run_ffmpeg(
        [
            "-y",
            "-ss",
            f"{clip_start:.3f}",
            "-i",
            str(source_path),
            "-t",
            f"{clip_duration:.3f}",
            *_VIDEO_ARGS,
            *_AUDIO_ARGS,
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    return clip_duration


def stitch_clips(clip_paths: list[str | Path], output_path: str | Path) -> None:
    """Concatenate ``clip_paths`` into a single reel at ``output_path``.

    Uses the ffmpeg concat demuxer with stream copy: all clips were re-encoded
    with identical parameters by :func:`extract_clip`, so no re-encode is needed.

    Raises:
        ClipExtractionError: If no clips are provided.
        FFmpegError: If the ffmpeg invocation fails.
    """
    if not clip_paths:
        raise ClipExtractionError("Cannot stitch an empty list of clips")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Single clip: copy straight through instead of running the concat demuxer.
    if len(clip_paths) == 1:
        run_ffmpeg(["-y", "-i", str(clip_paths[0]), "-c", "copy", "-movflags", "+faststart", str(output_path)])
        return

    concat_list_path = output_path.with_suffix(".concat.txt")
    concat_list_path.write_text(
        "".join(f"file '{_escape_concat_path(Path(p))}'\n" for p in clip_paths),
        encoding="utf-8",
    )
    try:
        run_ffmpeg(
            [
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list_path),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
        )
    finally:
        concat_list_path.unlink(missing_ok=True)


def _escape_concat_path(path: Path) -> str:
    # The concat demuxer treats single quotes specially; escape them.
    return str(path.resolve()).replace("'", "'\\''")

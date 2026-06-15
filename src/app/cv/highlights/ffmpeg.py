"""Thin, well-tested wrapper around the system ``ffmpeg`` / ``ffprobe`` binaries.

The highlight pipeline shells out to ffmpeg for frame-accurate clip extraction
and concat-demuxer stitching. Centralising the subprocess handling here keeps
call sites simple and gives us one place to surface a clear error if the binary
is missing from the image.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

FFMPEG_BINARY = "ffmpeg"
FFPROBE_BINARY = "ffprobe"

# Cap captured stderr so a pathological failure cannot blow up logs/exceptions.
_STDERR_TAIL_CHARS = 2000


class FFmpegError(RuntimeError):
    """Raised when an ffmpeg/ffprobe invocation fails or the binary is missing."""


def ensure_ffmpeg_available() -> None:
    """Raise :class:`FFmpegError` unless both ffmpeg and ffprobe are on PATH."""
    missing = [binary for binary in (FFMPEG_BINARY, FFPROBE_BINARY) if shutil.which(binary) is None]
    if missing:
        raise FFmpegError(
            f"Required binary not found on PATH: {', '.join(missing)}. "
            "Install ffmpeg (added to the Docker image apt-get layer)."
        )


def run_ffmpeg(args: list[str], *, timeout_sec: int | None = None) -> None:
    """Run ``ffmpeg`` with ``args`` (excluding the binary itself).

    ``-hide_banner`` and ``-nostdin`` are always prepended so the process never
    blocks waiting for interactive input.
    """
    ensure_ffmpeg_available()
    command = [FFMPEG_BINARY, "-hide_banner", "-nostdin", *args]
    completed = subprocess.run(  # noqa: S603 - fixed binary, no shell, args are controlled
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout_sec,
        check=False,
    )
    if completed.returncode != 0:
        stderr_tail = (completed.stderr or "")[-_STDERR_TAIL_CHARS:]
        raise FFmpegError(f"ffmpeg failed (exit {completed.returncode}): {stderr_tail.strip()}")


def probe_duration(path: str | Path) -> float:
    """Return the media duration in seconds via ``ffprobe``.

    Raises:
        FFmpegError: If ffprobe is missing, fails, or returns no usable duration.
    """
    ensure_ffmpeg_available()
    command = [
        FFPROBE_BINARY,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        str(path),
    ]
    completed = subprocess.run(  # noqa: S603 - fixed binary, no shell
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        stderr_tail = (completed.stderr or "")[-_STDERR_TAIL_CHARS:]
        raise FFmpegError(f"ffprobe failed (exit {completed.returncode}): {stderr_tail.strip()}")

    try:
        payload = json.loads(completed.stdout or "{}")
        duration = float(payload["format"]["duration"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise FFmpegError(f"ffprobe returned no usable duration for {path}") from exc

    if duration <= 0:
        raise FFmpegError(f"ffprobe returned non-positive duration for {path}")
    return duration


def has_audio_stream(path: str | Path) -> bool:
    """Return ``True`` when ``path`` contains at least one audio stream."""
    ensure_ffmpeg_available()
    command = [
        FFPROBE_BINARY,
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=index",
        "-of",
        "json",
        str(path),
    ]
    completed = subprocess.run(  # noqa: S603 - fixed binary, no shell
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return False
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return False
    return bool(payload.get("streams"))

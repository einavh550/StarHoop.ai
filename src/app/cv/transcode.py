"""Codec normalization and fps capping for the CV pipeline (Milestone 4).

Real-world uploads come from phones and cameras in whatever codec the device
prefers — increasingly AV1, which the ``ffmpeg`` that ``opencv-python-headless``
bundles cannot decode (``cv2.VideoCapture`` then yields zero frames and the
team classifier sees no players). To make ingestion codec-agnostic we re-encode
every video to H.264 / yuv420p using the *system* ``ffmpeg`` binary baked into
the Modal image (Ubuntu 22.04 ships the ``libdav1d`` AV1 software decoder), then
hand that normalized file to the pipeline. OpenCV can always read the result.

Phone recordings (especially from recent iOS/Android devices) are often 60 fps.
:func:`cap_fps` re-encodes those at ingest time to a target ceiling (default
30 fps), which roughly halves the frame count before the file ever reaches R2
or the Modal GPU workers — cutting both transfer time and processing cost.

This module shells out to ``ffmpeg``/``ffprobe`` via ``subprocess`` and is the
single place that knows the normalization recipe.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class TranscodeError(RuntimeError):
    """Raised when ffmpeg is unavailable or fails to normalize a video."""


def probe_codec(video_path: str | Path) -> str | None:
    """Return the source video stream codec name, or ``None`` if undetectable.

    Best-effort and never raises: a missing ``ffprobe`` or an unreadable file
    just yields ``None`` so callers can log it without failing the job.
    """
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return None

    try:
        result = subprocess.run(  # noqa: S603 - fixed binary, no shell
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    codec = result.stdout.strip()
    return codec or None


def probe_fps(video_path: str | Path) -> float | None:
    """Return the source frame rate as a float, or ``None`` if undetectable.

    Best-effort and never raises: a missing ``ffprobe`` or an unreadable file
    just yields ``None`` so callers can decide whether to skip the fps cap.

    ``r_frame_rate`` is returned by ffprobe as ``"num/den"`` (e.g. ``"60/1"``
    or ``"30000/1001"`` for 29.97 fps).
    """
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return None

    try:
        result = subprocess.run(  # noqa: S603 - fixed binary, no shell
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=r_frame_rate",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    raw = result.stdout.strip()
    if not raw:
        return None

    if "/" in raw:
        try:
            num, den = raw.split("/", 1)
            den_f = float(den)
            if den_f == 0:
                return None
            return float(num) / den_f
        except ValueError:
            return None

    try:
        return float(raw)
    except ValueError:
        return None


def cap_fps(src_path: str | Path, max_fps: int = 30) -> Path:
    """Re-encode ``src_path`` capped at ``max_fps`` and return the output path.

    If the source frame rate is already at or below ``max_fps`` the original
    path is returned unchanged — no ffmpeg invocation, no extra disk usage.

    When transcoding is needed, a sibling file ``<stem>_<max_fps>fps.mp4`` is
    written next to the source. The caller is responsible for deleting the
    original when the returned path differs from ``src_path``.

    Audio is preserved with stream-copy (``-c:a copy``) so the composed reel
    music pipeline can still mix game audio when needed.

    Raises:
        TranscodeError: if ffmpeg is required but unavailable or exits non-zero,
            or if the output file is empty.
    """
    src = Path(src_path)

    source_fps = probe_fps(src)
    # If fps is undetectable (ffprobe missing or unreadable file), skip capping
    # rather than risk a needless re-encode. Allow a 0.5 fps tolerance so
    # 29.97 (30000/1001) is not re-encoded when the cap is 30.
    if source_fps is None or source_fps <= max_fps + 0.5:
        return src

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise TranscodeError("ffmpeg binary not found on PATH; cannot cap frame rate.")

    dst = src.with_name(f"{src.stem}_{max_fps}fps.mp4")
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(src),
        "-vf",
        f"fps={max_fps}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(dst),
    ]

    try:
        result = subprocess.run(  # noqa: S603 - fixed binary, no shell
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise TranscodeError(f"Failed to invoke ffmpeg: {exc}") from exc

    if result.returncode != 0:
        tail = (result.stderr or "").strip().splitlines()[-5:]
        raise TranscodeError(
            f"ffmpeg failed to cap fps to {max_fps} "
            f"(exit {result.returncode}): {' | '.join(tail)}"
        )

    if not dst.exists() or dst.stat().st_size == 0:
        raise TranscodeError("ffmpeg produced an empty output file.")

    return dst


def normalize_video(src_path: str | Path, dst_path: str | Path | None = None) -> Path:
    """Re-encode ``src_path`` to H.264/yuv420p and return the output path.

    The output is OpenCV-readable regardless of the source codec (AV1, HEVC,
    etc.). Audio is dropped (``-an``) because the pipeline never uses it, and
    ``+faststart`` moves the moov atom to the front for fast frame seeking.

    Raises:
        TranscodeError: if ``ffmpeg`` is missing, exits non-zero, or produces an
            empty file.
    """
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise TranscodeError("ffmpeg binary not found on PATH; cannot normalize video.")

    src = Path(src_path)
    dst = Path(dst_path) if dst_path is not None else src.with_name(f"{src.stem}_normalized.mp4")

    command = [
        ffmpeg,
        "-y",
        "-i",
        str(src),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-pix_fmt",
        "yuv420p",
        "-an",
        "-movflags",
        "+faststart",
        str(dst),
    ]

    try:
        result = subprocess.run(  # noqa: S603 - fixed binary, no shell
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise TranscodeError(f"Failed to invoke ffmpeg: {exc}") from exc

    if result.returncode != 0:
        tail = (result.stderr or "").strip().splitlines()[-5:]
        raise TranscodeError(
            "ffmpeg failed to normalize video "
            f"(exit {result.returncode}): {' | '.join(tail)}"
        )

    if not dst.exists() or dst.stat().st_size == 0:
        raise TranscodeError("ffmpeg produced an empty output file.")

    return dst

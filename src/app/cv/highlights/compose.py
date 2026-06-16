"""ffmpeg composition engine for Milestone 6.

Turns the individual M5 highlight clips into a polished, share-ready reel:

1. Each clip is normalised to the target resolution (scale + letterbox pad),
   has its lower-third and brand watermark burned in, gets fade-in/out pacing,
   and its game audio ducked (or replaced with silence when the clip is mute).
2. An intro/title card image is rendered to a short video segment.
3. The intro + normalised clips are concatenated with the concat demuxer.
4. A looped music bed is mixed under the (already ducked) game audio.

Each step is a separate, individually testable ffmpeg argument builder so the
filter graphs can be asserted without invoking the binary.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app.cv.highlights.ffmpeg import (
    has_audio_stream,
    probe_duration,
    run_ffmpeg,
)

logger = logging.getLogger(__name__)

# Uniform encode params so every segment shares codec settings and the concat
# demuxer can stream-copy them together without re-encoding. CRF 18 + the high
# profile yields a visually lossless, deployment-ready master.
_VIDEO_ENCODE = [
    "-c:v",
    "libx264",
    "-preset",
    "slow",
    "-crf",
    "18",
    "-profile:v",
    "high",
    "-level",
    "4.2",
    "-pix_fmt",
    "yuv420p",
]
_AUDIO_ENCODE = ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
_FPS = 30
_SILENCE_INPUT = "anullsrc=channel_layout=stereo:sample_rate=48000"
# Subtle broadcast-style color grade + sharpening applied uniformly to every
# game clip so the reel looks consistent and punchy.
_COLOR_GRADE = "eq=contrast=1.06:saturation=1.12:brightness=0.012:gamma=0.98"
_SHARPEN = "unsharp=5:5:0.8:5:5:0.0"


class CompositionError(RuntimeError):
    """Raised when the ffmpeg composition pipeline cannot complete."""


@dataclass
class ClipSegment:
    """A single normalised segment to render before concatenation."""

    clip_path: Path
    lower_third_path: Path | None
    output_path: Path
    duration_sec: float | None = None


def _watermark_position(margin: int) -> str:
    return f"main_w-overlay_w-{margin}:main_h-overlay_h-{margin}"


def build_clip_args(
    segment: ClipSegment,
    *,
    width: int,
    height: int,
    transition_sec: float,
    duck_level: float,
    watermark_path: Path | None,
    has_audio: bool,
    fps: int = _FPS,
) -> list[str]:
    """Build the ffmpeg args that normalise + decorate one clip.

    ``segment.duration_sec`` must be populated so the fade-out can be timed.
    """
    duration = segment.duration_sec or 0.0
    fade = max(0.0, min(transition_sec, duration / 2)) if duration else transition_sec
    fade_out_start = max(0.0, duration - fade)
    margin = int(width * 0.03)

    inputs: list[str] = ["-i", str(segment.clip_path)]
    overlay_inputs: list[str] = []
    if segment.lower_third_path is not None:
        overlay_inputs.append(str(segment.lower_third_path))
    if watermark_path is not None:
        overlay_inputs.append(str(watermark_path))
    for overlay_path in overlay_inputs:
        inputs += ["-loop", "1", "-i", overlay_path]

    if not has_audio:
        inputs += ["-f", "lavfi", "-t", f"{duration:.3f}", "-i", _SILENCE_INPUT]

    # Video filter chain.
    chain = [
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1,fps={fps},format=yuv420p,"
        f"{_COLOR_GRADE},{_SHARPEN}[bg]"
    ]
    current = "[bg]"
    overlay_index = 1
    for _ in overlay_inputs:
        label = f"[ov{overlay_index}]"
        # The lower-third PNG is full-frame (position 0:0). The watermark, when
        # present, is always the final overlay and goes in the corner.
        if overlay_index == len(overlay_inputs) and watermark_path is not None:
            position = _watermark_position(margin)
        else:
            position = "0:0"
        chain.append(f"{current}[{overlay_index}:v]overlay={position}{label}")
        current = label
        overlay_index += 1

    if fade and duration:
        chain.append(
            f"{current}fade=t=in:st=0:d={fade:.3f},"
            f"fade=t=out:st={fade_out_start:.3f}:d={fade:.3f}[vout]"
        )
    else:
        chain.append(f"{current}null[vout]")

    # Audio filter chain.
    if has_audio:
        audio_source = "[0:a]"
    else:
        # The silence (anullsrc) input is added after the clip + every overlay.
        silence_index = 1 + len(overlay_inputs)
        audio_source = f"[{silence_index}:a]"
    audio_filters = [f"{audio_source}volume={duck_level:.3f}"]
    if fade and duration:
        audio_filters.append(f"afade=t=in:st=0:d={fade:.3f}")
        audio_filters.append(f"afade=t=out:st={fade_out_start:.3f}:d={fade:.3f}")
    audio_filters.append("aresample=48000")
    chain.append(",".join(audio_filters) + "[aout]")

    filter_complex = ";".join(chain)

    return [
        "-y",
        *inputs,
        "-filter_complex",
        filter_complex,
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        "-t",
        f"{duration:.3f}",
        *_VIDEO_ENCODE,
        *_AUDIO_ENCODE,
        "-movflags",
        "+faststart",
        str(segment.output_path),
    ]


def build_intro_args(
    intro_png: Path,
    *,
    width: int,
    height: int,
    duration_sec: float,
    transition_sec: float,
    output_path: Path,
    fps: int = _FPS,
) -> list[str]:
    """Build ffmpeg args that turn the intro card PNG into a short video."""
    fade = max(0.0, min(transition_sec, duration_sec / 2))
    fade_out_start = max(0.0, duration_sec - fade)
    return [
        "-y",
        "-loop",
        "1",
        "-t",
        f"{duration_sec:.3f}",
        "-i",
        str(intro_png),
        "-f",
        "lavfi",
        "-t",
        f"{duration_sec:.3f}",
        "-i",
        _SILENCE_INPUT,
        "-filter_complex",
        (
            f"[0:v]scale={width}:{height},setsar=1,fps={fps},format=yuv420p,"
            f"fade=t=in:st=0:d={fade:.3f},fade=t=out:st={fade_out_start:.3f}:d={fade:.3f}[vout]"
        ),
        "-map",
        "[vout]",
        "-map",
        "1:a",
        "-t",
        f"{duration_sec:.3f}",
        *_VIDEO_ENCODE,
        *_AUDIO_ENCODE,
        "-movflags",
        "+faststart",
        str(output_path),
    ]


def build_concat_args(concat_list_path: Path, output_path: Path) -> list[str]:
    """Build ffmpeg args to stream-copy concatenate the listed segments."""
    return [
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


def build_music_mix_args(
    video_path: Path,
    music_path: Path,
    *,
    music_volume: float,
    output_path: Path,
) -> list[str]:
    """Mix a looped music bed under the video's existing (ducked) audio."""
    return [
        "-y",
        "-i",
        str(video_path),
        "-stream_loop",
        "-1",
        "-i",
        str(music_path),
        "-filter_complex",
        (
            f"[1:a]volume={music_volume:.3f}[music];"
            "[0:a][music]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
            "loudnorm=I=-16:TP=-1.5:LRA=11[aout]"
        ),
        "-map",
        "0:v",
        "-map",
        "[aout]",
        "-c:v",
        "copy",
        *_AUDIO_ENCODE,
        "-shortest",
        "-movflags",
        "+faststart",
        str(output_path),
    ]


def _escape_concat_path(path: Path) -> str:
    # The concat demuxer resolves relative entries against the directory that
    # holds the concat list, so always emit an absolute path. Single quotes are
    # special to the demuxer and must be escaped.
    absolute = path.resolve().as_posix()
    return absolute.replace("'", "'\\''")


def write_concat_list(segment_paths: list[Path], list_path: Path) -> Path:
    """Write a concat-demuxer playlist for ``segment_paths``."""
    list_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"file '{_escape_concat_path(path)}'" for path in segment_paths]
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return list_path


def render_composition(
    *,
    clip_specs: list[ClipSegment],
    intro_png: Path | None,
    width: int,
    height: int,
    transition_sec: float,
    intro_duration_sec: float,
    duck_level: float,
    music_volume: float,
    watermark_path: Path | None,
    music_path: Path | None,
    work_dir: Path,
    output_path: Path,
    timeout_sec: int = 1800,
) -> float:
    """Render the full composition and return its duration in seconds.

    Raises:
        CompositionError: If no clips are provided or an ffmpeg step fails.
    """
    if not clip_specs:
        raise CompositionError("Cannot compose a reel with no clips")

    work_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    segment_paths: list[Path] = []

    # 1. Intro segment.
    if intro_png is not None:
        intro_segment = work_dir / "seg_000_intro.mp4"
        run_ffmpeg(
            build_intro_args(
                intro_png,
                width=width,
                height=height,
                duration_sec=intro_duration_sec,
                transition_sec=transition_sec,
                output_path=intro_segment,
            ),
            timeout_sec=timeout_sec,
        )
        segment_paths.append(intro_segment)

    # 2. Per-clip normalised segments.
    for index, spec in enumerate(clip_specs, start=1):
        if not spec.clip_path.exists():
            logger.warning("Skipping missing clip during compose: %s", spec.clip_path)
            continue
        spec.duration_sec = spec.duration_sec or probe_duration(spec.clip_path)
        spec.output_path = work_dir / f"seg_{index:03d}.mp4"
        run_ffmpeg(
            build_clip_args(
                spec,
                width=width,
                height=height,
                transition_sec=transition_sec,
                duck_level=duck_level,
                watermark_path=watermark_path,
                has_audio=has_audio_stream(spec.clip_path),
            ),
            timeout_sec=timeout_sec,
        )
        segment_paths.append(spec.output_path)

    if not segment_paths or (intro_png is not None and len(segment_paths) == 1):
        raise CompositionError("No usable clip segments were produced for composition")

    # 3. Concatenate.
    concat_list = write_concat_list(segment_paths, work_dir / "concat.txt")
    concat_output = work_dir / "concat.mp4"
    run_ffmpeg(build_concat_args(concat_list, concat_output), timeout_sec=timeout_sec)

    # 4. Music bed mix (or just promote the concat output when no music).
    if music_path is not None and music_path.exists():
        run_ffmpeg(
            build_music_mix_args(
                concat_output,
                music_path,
                music_volume=music_volume,
                output_path=output_path,
            ),
            timeout_sec=timeout_sec,
        )
    else:
        run_ffmpeg(build_concat_args(concat_list, output_path), timeout_sec=timeout_sec)

    return probe_duration(output_path)

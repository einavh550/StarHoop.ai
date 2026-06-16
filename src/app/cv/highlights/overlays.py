"""Pillow-based graphics for Milestone 6 reel composition.

Pure rendering helpers that produce PNGs ffmpeg later composites onto the video:

* :func:`render_intro_card` -- a full-frame title card (player identity, team,
  optional event-count stats, brand logo and player photo).
* :func:`render_lower_third` -- a transparent full-frame overlay with a bottom
  name/number band plus an event chip, burned onto each clip.
* :func:`render_watermark` -- the brand logo resized with opacity for a
  persistent corner watermark.

Everything degrades gracefully: missing fonts fall back to Pillow's default and
missing images are simply skipped, so a composition never fails on cosmetics.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.cv.highlights.events import (
    EVENT_BALL_IN_BASKET,
    EVENT_JUMP_SHOT,
    EVENT_LAYUP_DUNK,
    EVENT_POSSESSION,
    EVENT_SHOT_ATTEMPT,
    EVENT_SHOT_BLOCK,
)

logger = logging.getLogger(__name__)

# Default theme (no per-team colors in M6 scope).
_BG_TOP = (11, 18, 38)       # deep navy
_BG_BOTTOM = (24, 38, 74)    # lighter navy
_ACCENT = (255, 140, 0)      # StarHoop orange
_TEXT = (245, 247, 252)
_TEXT_MUTED = (176, 186, 208)
_BAND = (0, 0, 0, 165)       # translucent black band for the lower third

_EVENT_LABELS: dict[str, str] = {
    EVENT_SHOT_ATTEMPT: "Shot",
    EVENT_LAYUP_DUNK: "Layup / Dunk",
    EVENT_JUMP_SHOT: "Jump Shot",
    EVENT_SHOT_BLOCK: "Block",
    EVENT_POSSESSION: "Possession",
    EVENT_BALL_IN_BASKET: "Bucket",
}


def humanize_event(event_type: str) -> str:
    """Return a human-friendly label for an internal event type."""
    return _EVENT_LABELS.get(event_type, event_type.replace("_", " ").title())


@dataclass(frozen=True)
class ReelStats:
    """Event-count summary derived from the clips in a reel."""

    total_clips: int
    made_shots: int
    counts: dict[str, int] = field(default_factory=dict)

    def summary_lines(self) -> list[str]:
        """Return display lines for the intro card stats block."""
        lines = [f"{self.total_clips} HIGHLIGHTS"]
        ordered = (
            EVENT_LAYUP_DUNK,
            EVENT_JUMP_SHOT,
            EVENT_SHOT_ATTEMPT,
            EVENT_BALL_IN_BASKET,
            EVENT_SHOT_BLOCK,
            EVENT_POSSESSION,
        )
        for event_type in ordered:
            count = self.counts.get(event_type, 0)
            if count:
                lines.append(f"{count}  {humanize_event(event_type)}")
        if self.made_shots:
            lines.append(f"{self.made_shots}  Made")
        return lines


def compute_stats(clips: Iterable) -> ReelStats:
    """Aggregate event counts and made shots from highlight clip rows/objects."""
    counts: dict[str, int] = {}
    made_shots = 0
    total = 0
    for clip in clips:
        total += 1
        event_type = getattr(clip, "event_type", None)
        if event_type:
            counts[event_type] = counts.get(event_type, 0) + 1
        if getattr(clip, "made", None) is True:
            made_shots += 1
    return ReelStats(total_clips=total, made_shots=made_shots, counts=counts)


def _load_font(font_path: str | None, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if font_path and Path(font_path).exists():
        try:
            return ImageFont.truetype(font_path, size=size)
        except OSError:
            logger.warning("Falling back to default font; could not load %s", font_path)
    return ImageFont.load_default()


def _text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return right - left, bottom - top


def _vertical_gradient(size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    width, height = size
    base = Image.new("RGB", size, top)
    top_r, top_g, top_b = top
    bottom_r, bottom_g, bottom_b = bottom
    for y in range(height):
        ratio = y / max(height - 1, 1)
        row = (
            int(top_r + (bottom_r - top_r) * ratio),
            int(top_g + (bottom_g - top_g) * ratio),
            int(top_b + (bottom_b - top_b) * ratio),
        )
        ImageDraw.Draw(base).line([(0, y), (width, y)], fill=row)
    return base


def _fit_circle(image: Image.Image, diameter: int) -> Image.Image:
    """Return ``image`` center-cropped to a square and masked into a circle."""
    source = image.convert("RGBA")
    side = min(source.size)
    left = (source.width - side) // 2
    top = (source.height - side) // 2
    cropped = source.crop((left, top, left + side, top + side)).resize((diameter, diameter), Image.LANCZOS)

    mask = Image.new("L", (diameter, diameter), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, diameter - 1, diameter - 1), fill=255)
    circled = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    circled.paste(cropped, (0, 0), mask)
    return circled


def _circular_logo(image: Image.Image, diameter: int, *, pad_ratio: float = 0.12) -> Image.Image:
    """Fit ``image`` fully inside a transparent circle (no content is cropped).

    Unlike :func:`_fit_circle` (which center-crops a photo to fill the circle),
    this contains the whole logo inside the circle on a transparent background so
    wordmarks are never clipped.
    """
    source = image.convert("RGBA")
    inner = max(1, int(diameter * (1.0 - pad_ratio)))
    scale = min(inner / source.width, inner / source.height)
    new_size = (max(1, int(source.width * scale)), max(1, int(source.height * scale)))
    resized = source.resize(new_size, Image.LANCZOS)

    circled = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    offset = ((diameter - new_size[0]) // 2, (diameter - new_size[1]) // 2)
    circled.paste(resized, offset, resized)

    mask = Image.new("L", (diameter, diameter), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, diameter - 1, diameter - 1), fill=255)
    circled.putalpha(Image.composite(circled.getchannel("A"), Image.new("L", (diameter, diameter), 0), mask))
    return circled


def render_intro_card(
    output_path: str | Path,
    *,
    width: int,
    height: int,
    title: str,
    subtitle: str,
    stats_lines: Sequence[str] | None = None,
    photo_path: str | Path | None = None,
    logo_path: str | Path | None = None,
    font_path: str | None = None,
    font_bold_path: str | None = None,
) -> str:
    """Render a full-frame intro/title card PNG and return its path."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    card = _vertical_gradient((width, height), _BG_TOP, _BG_BOTTOM).convert("RGBA")
    draw = ImageDraw.Draw(card)

    margin = int(width * 0.04)
    title_font = _load_font(font_bold_path or font_path, max(28, int(height * 0.072)))
    subtitle_font = _load_font(font_path, max(18, int(height * 0.040)))
    stats_header_font = _load_font(font_bold_path or font_path, max(18, int(height * 0.044)))
    stats_font = _load_font(font_path, max(16, int(height * 0.038)))

    # Brand logo: circular, transparent, pinned to the TOP-LEFT corner so it
    # never overlaps the centered player photo.
    if logo_path and Path(str(logo_path)).exists():
        try:
            with Image.open(logo_path) as raw_logo:
                logo = _circular_logo(raw_logo, int(height * 0.13))
            card.alpha_composite(logo, (margin, margin))
        except OSError:
            logger.warning("Could not load brand logo for intro card: %s", logo_path)

    # Player photo as a centered circle near the top third.
    photo_diameter = int(height * 0.30)
    photo_center_y = int(height * 0.29)
    if photo_path and Path(str(photo_path)).exists():
        try:
            with Image.open(photo_path) as raw_photo:
                circle = _fit_circle(raw_photo, photo_diameter)
            ring = Image.new("RGBA", (photo_diameter + 12, photo_diameter + 12), (0, 0, 0, 0))
            ImageDraw.Draw(ring).ellipse(
                (0, 0, photo_diameter + 11, photo_diameter + 11), outline=_ACCENT, width=6
            )
            card.alpha_composite(ring, ((width - ring.width) // 2, photo_center_y - ring.height // 2))
            card.alpha_composite(circle, ((width - photo_diameter) // 2, photo_center_y - photo_diameter // 2))
        except OSError:
            logger.warning("Could not load player photo for intro card: %s", photo_path)

    # Title (player name + number) and subtitle (team / season).
    title_w, title_h = _text_size(draw, title, title_font)
    title_y = int(height * 0.49)
    draw.text(((width - title_w) // 2, title_y), title, font=title_font, fill=_TEXT)

    # Accent underline spans the FULL title width (name + number as one unit).
    accent_h = max(4, int(height * 0.009))
    accent_pad = int(width * 0.015)
    accent_w = title_w + accent_pad * 2
    accent_y = title_y + title_h + int(height * 0.018)
    draw.rounded_rectangle(
        (
            (width - accent_w) // 2,
            accent_y,
            (width + accent_w) // 2,
            accent_y + accent_h,
        ),
        radius=accent_h // 2,
        fill=_ACCENT,
    )

    subtitle_w, subtitle_h = _text_size(draw, subtitle, subtitle_font)
    subtitle_y = accent_y + accent_h + int(height * 0.022)
    draw.text(
        ((width - subtitle_w) // 2, subtitle_y),
        subtitle,
        font=subtitle_font,
        fill=_TEXT_MUTED,
    )

    # Stats block: a single cohesive, evenly spaced column with no large gap.
    if stats_lines:
        line_height = int(height * 0.050)
        start_y = subtitle_y + subtitle_h + int(height * 0.045)
        for index, line in enumerate(stats_lines):
            line_font = stats_header_font if index == 0 else stats_font
            fill = _ACCENT if index == 0 else _TEXT_MUTED
            line_w, _ = _text_size(draw, line, line_font)
            draw.text(((width - line_w) // 2, start_y + index * line_height), line, font=line_font, fill=fill)

    card.convert("RGB").save(output_path, format="PNG")
    return str(output_path)


def render_lower_third(
    output_path: str | Path,
    *,
    width: int,
    height: int,
    primary: str,
    secondary: str | None = None,
    font_path: str | None = None,
    font_bold_path: str | None = None,
) -> str:
    """Render a transparent full-frame overlay with a bottom name/event band."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    band_height = int(height * 0.16)
    band_top = height - band_height
    draw.rectangle((0, band_top, width, height), fill=_BAND)
    draw.rectangle((0, band_top, int(width * 0.012), height), fill=_ACCENT)

    # Smaller, tighter type so the name and the event chip never collide.
    primary_font = _load_font(font_bold_path or font_path, max(18, int(band_height * 0.30)))
    pad_x = int(width * 0.03)
    primary_y = band_top + int(band_height * 0.16)
    draw.text((pad_x, primary_y), primary, font=primary_font, fill=_TEXT)

    if secondary:
        secondary_font = _load_font(font_path, max(12, int(band_height * 0.22)))
        chip_w, chip_h = _text_size(draw, secondary, secondary_font)
        chip_pad_x = int(band_height * 0.14)
        chip_pad_y = int(band_height * 0.10)
        chip_x = pad_x
        chip_y = band_top + int(band_height * 0.62)
        draw.rounded_rectangle(
            (
                chip_x - chip_pad_x // 2,
                chip_y - chip_pad_y,
                chip_x + chip_w + chip_pad_x,
                chip_y + chip_h + chip_pad_y,
            ),
            radius=int((chip_h + chip_pad_y * 2) * 0.5),
            fill=_ACCENT,
        )
        draw.text((chip_x + chip_pad_x // 2, chip_y), secondary, font=secondary_font, fill=(20, 24, 40))

    overlay.save(output_path, format="PNG")
    return str(output_path)


def render_watermark(
    output_path: str | Path,
    *,
    logo_path: str | Path,
    target_width: int,
    opacity: float,
) -> str | None:
    """Resize ``logo_path`` to ``target_width`` and apply ``opacity`` (0-1).

    Returns the output path, or ``None`` if the logo could not be loaded.
    """
    if not logo_path or not Path(str(logo_path)).exists():
        return None
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with Image.open(logo_path) as raw_logo:
            logo = _circular_logo(raw_logo, target_width)
    except OSError:
        logger.warning("Could not load watermark logo: %s", logo_path)
        return None

    alpha = logo.getchannel("A").point(lambda value: int(value * max(0.0, min(1.0, opacity))))
    logo.putalpha(alpha)
    logo.save(output_path, format="PNG")
    return str(output_path)

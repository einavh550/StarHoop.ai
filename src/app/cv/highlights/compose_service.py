"""Orchestrate professional reel composition (Milestone 6).

Takes a completed Milestone 5 :class:`HighlightReel` and renders a polished,
share-ready product: an intro/title card, per-clip lower-thirds, a brand
watermark, fade transitions and a ducked music bed.

The brand assets (music + logo) and the player photo live in Cloudflare R2 (see
the asset upload routes), so this layer pulls the chosen objects down to a temp
work directory before handing local paths to the Pillow/ffmpeg engines. The
:class:`ComposedReel` row is created ``processing`` up front and flipped to a
terminal ``completed`` / ``failed`` state so a crash never leaves a silent gap.
Each call creates a new composition (styling history is preserved).
"""

from __future__ import annotations

import logging
import shutil
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.cv import r2_storage
from app.cv.highlights import audio, compose, overlays
from app.cv.storage import ensure_storage_directory
from app.db.models import ComposedReel, HighlightReel, Player, Team, VideoJob

logger = logging.getLogger(__name__)

_VALID_ASPECTS = {"16:9", "9:16"}


class CompositionRequestError(RuntimeError):
    """Base error for invalid composition requests."""


class ReelNotReadyError(CompositionRequestError):
    """The source M5 reel is missing, not completed, or has no clips."""


def _target_dimensions(aspect_ratio: str) -> tuple[int, int]:
    """Return (width, height) for the requested aspect, height from config."""
    height = settings.compose_video_height
    if aspect_ratio == "9:16":
        # Vertical: swap so the long edge is the height.
        return height, int(round(height * 16 / 9))
    return int(round(height * 16 / 9)), height


def _player_name(player: Player | None) -> str:
    if player is None:
        return ""
    return player.full_name or f"Player #{player.jersey_number}"


def _resolve_logo_key() -> str | None:
    keys = r2_storage.list_keys(settings.compose_branding_prefix)
    return keys[0] if keys else None


def compose_reel(
    db: Session,
    *,
    job_id: int,
    reel_id: int,
    aspect_ratio: str | None = None,
    music_track: str | None = None,
    include_intro: bool = True,
    include_stats: bool = True,
    include_watermark: bool = True,
) -> ComposedReel:
    """Compose a polished reel from M5 reel ``reel_id`` and persist it.

    Raises:
        CompositionRequestError: Invalid aspect ratio or unknown music track.
        ReelNotReadyError: Source reel missing / not completed / has no clips.
        compose.CompositionError / FFmpegError: Media processing failed.
    """
    aspect = aspect_ratio or settings.compose_default_aspect
    if aspect not in _VALID_ASPECTS:
        raise CompositionRequestError(
            f"Invalid aspect_ratio '{aspect}'. Expected one of: {sorted(_VALID_ASPECTS)}"
        )

    job = db.query(VideoJob).filter(VideoJob.id == job_id).first()
    if job is None:
        raise ReelNotReadyError(f"VideoJob {job_id} not found")

    reel = (
        db.query(HighlightReel)
        .filter(HighlightReel.id == reel_id, HighlightReel.video_job_id == job_id)
        .first()
    )
    if reel is None:
        raise ReelNotReadyError(f"Highlight reel {reel_id} not found for job {job_id}")
    if reel.status != "completed":
        raise ReelNotReadyError(
            f"Highlight reel {reel_id} is not completed (status={reel.status})"
        )

    clips = sorted(reel.clips, key=lambda clip: clip.order_index)
    clip_paths = [Path(clip.clip_path) for clip in clips if clip.clip_path]
    if not clip_paths:
        raise ReelNotReadyError(f"Highlight reel {reel_id} has no clips to compose")

    player = reel.player if reel.player_id is not None else None
    team = db.query(Team).filter(Team.id == job.team_id).first()

    # Resolve the music track up front so an unknown name fails fast.
    music_key = audio.select_music_key(music_track)

    width, height = _target_dimensions(aspect)
    stats = overlays.compute_stats(clips)

    composed = ComposedReel(
        reel_id=reel.id,
        video_job_id=job_id,
        player_id=reel.player_id,
        status="processing",
        aspect_ratio=aspect,
        music_track=music_key,
        has_intro=include_intro,
        has_stats=include_stats and include_intro,
        has_watermark=include_watermark,
        total_duration_sec=Decimal("0.000"),
    )
    db.add(composed)
    db.commit()
    db.refresh(composed)

    export_root = Path(ensure_storage_directory(settings.compose_export_dir))
    composed_dir = export_root / f"job_{job_id}" / f"composed_{composed.id}"
    work_dir = Path(settings.compose_work_dir) / f"composed_{composed.id}"
    assets_dir = work_dir / "assets"
    composed_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    try:
        # --- Pull R2 assets to local temp files. -----------------------------
        music_path: Path | None = None
        if music_key:
            music_path = assets_dir / Path(music_key).name
            r2_storage.download_file(music_key, music_path)

        logo_path: Path | None = None
        logo_key = _resolve_logo_key()
        if logo_key:
            logo_path = assets_dir / Path(logo_key).name
            r2_storage.download_file(logo_key, logo_path)

        photo_path: Path | None = None
        if player is not None and player.photo_url:
            photo_path = assets_dir / Path(player.photo_url).name
            try:
                r2_storage.download_file(player.photo_url, photo_path)
            except Exception:  # noqa: BLE001 - cosmetic asset, never fatal
                logger.warning("Could not download player photo %s; continuing", player.photo_url)
                photo_path = None

        # --- Render graphics. ------------------------------------------------
        intro_png: Path | None = None
        if include_intro:
            if player is not None:
                title = _player_name(player)
                if player.jersey_number is not None:
                    title = f"{title}  #{player.jersey_number}"
                subtitle = team.name if team else "HoopStar.ai"
                if team and team.season:
                    subtitle = f"{subtitle} · {team.season}"
            else:
                title = team.name if team else "Team Highlights"
                subtitle = f"{team.season} Season" if team and team.season else "Season Highlights"

            intro_png = work_dir / "intro.png"
            overlays.render_intro_card(
                intro_png,
                width=width,
                height=height,
                title=title,
                subtitle=subtitle,
                stats_lines=stats.summary_lines() if include_stats else None,
                photo_path=photo_path,
                logo_path=logo_path,
                font_path=settings.compose_font_path,
                font_bold_path=settings.compose_font_bold_path,
            )

        watermark_path: Path | None = None
        if include_watermark and logo_path is not None:
            watermark_path = overlays.render_watermark(
                work_dir / "watermark.png",
                logo_path=logo_path,
                target_width=int(width * 0.16),
                opacity=settings.compose_watermark_opacity,
            )
            watermark_path = Path(watermark_path) if watermark_path else None

        # --- Build per-clip lower-thirds + segment specs. --------------------
        clip_specs: list[compose.ClipSegment] = []
        for index, clip in enumerate(clips):
            if not clip.clip_path or not Path(clip.clip_path).exists():
                continue
            primary = _player_name(player) if player is not None else (team.name if team else "Highlight")
            if player is not None and player.jersey_number is not None:
                primary = f"{primary}  #{player.jersey_number}"
            lower_third = work_dir / f"lower_{index:03d}.png"
            overlays.render_lower_third(
                lower_third,
                width=width,
                height=height,
                primary=primary,
                secondary=overlays.humanize_event(clip.event_type),
                font_path=settings.compose_font_path,
                font_bold_path=settings.compose_font_bold_path,
            )
            clip_specs.append(
                compose.ClipSegment(
                    clip_path=Path(clip.clip_path),
                    lower_third_path=lower_third,
                    output_path=work_dir / f"seg_{index:03d}.mp4",
                )
            )

        # --- Render the composition. -----------------------------------------
        output_filename = f"composed_{composed.id}_{aspect.replace(':', 'x')}.mp4"
        output_path = composed_dir / output_filename
        total_duration = compose.render_composition(
            clip_specs=clip_specs,
            intro_png=intro_png,
            width=width,
            height=height,
            transition_sec=settings.compose_transition_sec,
            intro_duration_sec=settings.compose_intro_duration_sec,
            duck_level=settings.compose_duck_level,
            music_volume=settings.compose_music_volume,
            watermark_path=watermark_path,
            music_path=music_path,
            work_dir=work_dir,
            output_path=output_path,
        )

        composed.status = "completed"
        composed.total_duration_sec = Decimal(f"{total_duration:.3f}")
        composed.output_path = str(output_path.resolve())
        composed.output_filename = output_filename
        db.commit()
        db.refresh(composed)
        logger.info(
            "composed_reel_created job_id=%s reel_id=%s composed_id=%s clips=%s aspect=%s",
            job_id,
            reel.id,
            composed.id,
            len(clip_specs),
            aspect,
        )
        return composed
    except Exception as exc:
        db.rollback()
        _mark_composed_failed(db, composed.id, exc)
        shutil.rmtree(composed_dir, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _mark_composed_failed(db: Session, composed_id: int, exc: Exception) -> None:
    """Best-effort: flip the composition to ``failed`` with a short message."""
    try:
        composed = db.query(ComposedReel).filter(ComposedReel.id == composed_id).first()
        if composed is not None:
            composed.status = "failed"
            composed.error_message = str(exc)[:1024]
            db.commit()
    except Exception:
        db.rollback()
        logger.exception("failed to mark composed reel %s as failed", composed_id)

"""Music selection for Milestone 6 reel composition.

The brand-supplied music tracks live in R2 under ``settings.compose_music_prefix``
(see the asset upload routes). This module picks which track to use for a
composition and exposes the chosen R2 key so the orchestration layer can pull it
to a temp file for ffmpeg. The actual audio mixing (music bed + ducked game
audio) is built in :mod:`app.cv.highlights.compose`.
"""

from __future__ import annotations

import logging
from pathlib import PurePosixPath

from app.cv import r2_storage
from app.core.config import settings

logger = logging.getLogger(__name__)


class MusicUnavailableError(RuntimeError):
    """Raised when a composition requests music but none can be resolved."""


def _basename(key: str) -> str:
    return PurePosixPath(key).name


def list_music_keys() -> list[str]:
    """Return every music object key available in R2 (sorted, deduplicated)."""
    return r2_storage.list_keys(settings.compose_music_prefix)


def select_music_key(requested: str | None = None) -> str | None:
    """Resolve which R2 music key to use.

    * ``requested`` may be a full key or just a filename; the first matching
      object (case-insensitive) is returned.
    * When ``requested`` is ``None`` the first available track is used.
    * Returns ``None`` when no music exists at all (composition proceeds silent).
    """
    keys = list_music_keys()
    if not keys:
        logger.info("No music tracks available under %s", settings.compose_music_prefix)
        return None

    if requested:
        needle = requested.strip().lower()
        for key in keys:
            if key.lower() == needle or _basename(key).lower() == needle:
                return key
        raise MusicUnavailableError(
            f"Requested music track '{requested}' not found among {len(keys)} available tracks"
        )

    return keys[0]

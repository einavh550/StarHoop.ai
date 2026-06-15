"""Copy locally uploaded asset files into Cloudflare R2.

This is a one-time migration helper for the assets already uploaded before the
asset endpoints were switched to R2 persistence.
"""

from __future__ import annotations

import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path

import boto3
from botocore.config import Config
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Player
from app.db.session import SessionLocal


@dataclass(frozen=True)
class MigratedAsset:
    local_path: Path
    storage_key: str


def _build_client():
    endpoint = os.environ.get("R2_ENDPOINT_URL") or f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def _content_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or {
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
    }.get(path.suffix.lower(), "application/octet-stream")


def _upload_directory(base_dir: Path, prefix: str) -> list[MigratedAsset]:
    migrated: list[MigratedAsset] = []
    if not base_dir.exists():
        return migrated

    client = _build_client()
    bucket = os.environ["R2_BUCKET"]

    for local_path in sorted(path for path in base_dir.rglob("*") if path.is_file()):
        relative_name = local_path.relative_to(base_dir).as_posix()
        storage_key = f"assets/{prefix}/{relative_name}"
        client.upload_file(
            Filename=str(local_path),
            Bucket=bucket,
            Key=storage_key,
            ExtraArgs={"ContentType": _content_type(local_path)},
        )
        migrated.append(MigratedAsset(local_path=local_path, storage_key=storage_key))
    return migrated


def _migrate_player_photos(db: Session, base_dir: Path) -> list[MigratedAsset]:
    migrated: list[MigratedAsset] = []
    if not base_dir.exists():
        return migrated

    client = _build_client()
    bucket = os.environ["R2_BUCKET"]

    grouped: dict[tuple[int, int], list[Path]] = {}
    for local_path in sorted(path for path in base_dir.rglob("*") if path.is_file()):
        parts = local_path.relative_to(base_dir).parts
        if len(parts) < 3:
            continue
        try:
            team_id = int(parts[0].split("team_")[1])
            jersey_number = int(parts[1].split("jersey_")[1])
        except (IndexError, ValueError):
            continue
        grouped.setdefault((team_id, jersey_number), []).append(local_path)

    for (team_id, jersey_number), files in grouped.items():
        latest_local_path = max(files, key=lambda path: path.stat().st_mtime)
        for local_path in files:
            storage_key = f"assets/players/team_{team_id}/jersey_{jersey_number}/{local_path.name}"
            client.upload_file(
                Filename=str(local_path),
                Bucket=bucket,
                Key=storage_key,
                ExtraArgs={"ContentType": _content_type(local_path)},
            )
            migrated.append(MigratedAsset(local_path=local_path, storage_key=storage_key))

        player = (
            db.query(Player)
            .filter(Player.team_id == team_id, Player.jersey_number == jersey_number)
            .first()
        )
        if player is not None:
            latest_key = f"assets/players/team_{team_id}/jersey_{jersey_number}/{latest_local_path.name}"
            player.photo_url = latest_key
            db.commit()

    return migrated


def main() -> None:
    db = SessionLocal()
    try:
        music_assets = _upload_directory(Path(settings.music_asset_dir), "music")
        branding_assets = _upload_directory(Path(settings.branding_asset_dir), "branding")
        player_assets = _migrate_player_photos(db, Path(settings.player_photo_asset_dir))

        summary_lines = [
            f"Migrated {len(music_assets)} music files",
            f"Migrated {len(branding_assets)} branding files",
            f"Migrated {len(player_assets)} player photo files",
        ]
        summary_text = "\n".join(summary_lines) + "\n"
        print(summary_text, end="")
        Path("/tmp/migrate_assets_to_r2_result.txt").write_text(summary_text, encoding="utf-8")
    finally:
        db.close()


if __name__ == "__main__":
    main()
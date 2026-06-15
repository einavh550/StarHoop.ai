"""Asset upload endpoints for music, branding, and player photos."""

from contextlib import suppress
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.cv.schemas import AssetUploadResponse, PlayerPhotoUploadResponse
from app.cv import r2_storage
from app.cv.storage import parse_allowed_extensions, save_upload_file
from app.db.models import Player, Team
from app.db.session import get_db

router = APIRouter(prefix="/api/assets", tags=["assets"])

_MUSIC_EXTENSIONS = parse_allowed_extensions(".mp3,.m4a,.aac,.wav,.ogg,.flac")
_IMAGE_EXTENSIONS = parse_allowed_extensions(".png,.jpg,.jpeg,.webp")


def _asset_key(asset_type: str, stored_filename: str) -> str:
    return f"assets/{asset_type}/{stored_filename}"


def _asset_download_url(key: str) -> str | None:
    with suppress(Exception):
        return r2_storage.generate_presigned_get_url(key)
    return None


async def _save_asset(
    upload_file: UploadFile,
    storage_dir: str,
    allowed_extensions: set[str],
    asset_type: str,
) -> AssetUploadResponse:
    try:
        original_filename, storage_path = await save_upload_file(
            upload_file=upload_file,
            storage_dir=storage_dir,
            max_size_mb=settings.max_upload_size_mb,
            allowed_extensions=allowed_extensions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    stored_path = Path(storage_path)
    storage_key = _asset_key(asset_type, stored_path.name)
    try:
        r2_storage.upload_file(local_path=str(stored_path), key=storage_key)
    except Exception as exc:  # noqa: BLE001
        with suppress(Exception):
            stored_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to persist {asset_type} to R2: {exc}",
        ) from exc
    with suppress(Exception):
        stored_path.unlink(missing_ok=True)

    return AssetUploadResponse(
        asset_type=asset_type,
        original_filename=original_filename,
        stored_filename=stored_path.name,
        storage_key=storage_key,
        download_url=_asset_download_url(storage_key),
        message=f"{asset_type.replace('_', ' ').title()} uploaded successfully.",
    )


@router.post("/music", response_model=AssetUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_music(file: UploadFile = File(...)) -> AssetUploadResponse:
    return await _save_asset(
        upload_file=file,
        storage_dir=settings.music_asset_dir,
        allowed_extensions=_MUSIC_EXTENSIONS,
        asset_type="music",
    )


@router.post("/branding/logo", response_model=AssetUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_brand_logo(file: UploadFile = File(...)) -> AssetUploadResponse:
    return await _save_asset(
        upload_file=file,
        storage_dir=settings.branding_asset_dir,
        allowed_extensions=_IMAGE_EXTENSIONS,
        asset_type="branding_logo",
    )


@router.post("/players/photo", response_model=PlayerPhotoUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_player_photo(
    team_id: int = Form(...),
    jersey_number: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> PlayerPhotoUploadResponse:
    team = db.query(Team).filter(Team.id == team_id).first()
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Team {team_id} was not found.")

    player = db.query(Player).filter(Player.team_id == team_id, Player.jersey_number == jersey_number).first()
    if player is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Player with jersey number {jersey_number} was not found on team {team_id}.",
        )

    storage_dir = Path(settings.player_photo_asset_dir) / f"team_{team_id}" / f"jersey_{jersey_number}"
    saved_asset = await _save_asset(
        upload_file=file,
        storage_dir=str(storage_dir),
        allowed_extensions=_IMAGE_EXTENSIONS,
        asset_type="player_photo",
    )

    player.photo_url = saved_asset.storage_key
    db.commit()

    return PlayerPhotoUploadResponse(
        **saved_asset.model_dump(),
        team_id=team_id,
        jersey_number=jersey_number,
        player_id=player.id,
        player_name=player.full_name,
        photo_url=player.photo_url or saved_asset.storage_key,
    )
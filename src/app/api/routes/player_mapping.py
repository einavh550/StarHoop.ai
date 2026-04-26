"""
Player mapping endpoints for Milestone 3 Phase 2.

Maps detected jersey numbers to actual players based on team roster.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.cv.mapping import PlayerMapper
from app.cv.schemas import PlayerMappingResponse, PlayerMappingSuggestion
from app.db.models import VideoJob

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/videos", tags=["player_mapping"])


@router.post("/{job_id}/player_mapping/auto")
async def auto_map_players(
    job_id: int,
    team_id: Annotated[int, Query(..., description="Team ID for player lookup")],
    db: Session = Depends(get_db),
) -> PlayerMappingResponse:
    """
    Automatically map detected jerseys to players based on team roster.
    
    Aggregates jersey detections from detection_frames, matches to Player records,
    and returns mapping suggestions with confidence ratings.
    
    Args:
        job_id: VideoJob ID to process
        team_id: Team ID for roster lookup
        db: Database session
    
    Returns:
        PlayerMappingResponse with suggested player mappings
    
    Raises:
        HTTPException 404: If video job not found
        HTTPException 400: If team_id doesn't match job.team_id
    """
    try:
        # Fetch video job
        job = db.query(VideoJob).filter(VideoJob.id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail=f"VideoJob {job_id} not found")
        
        if job.team_id != team_id:
            raise HTTPException(
                status_code=400,
                detail=f"VideoJob {job_id} belongs to team {job.team_id}, not {team_id}"
            )
        
        # Aggregate jerseys
        aggregated = PlayerMapper.aggregate_jerseys_from_video(db, job_id, team_id)
        
        if not aggregated:
            logger.warning(f"No jersey detections found for job {job_id}")
            return PlayerMappingResponse(
                job_id=job_id,
                team_id=team_id,
                total_mappings=0,
                high_confidence_count=0,
                medium_confidence_count=0,
                low_confidence_count=0,
                no_match_count=0,
                mappings=[],
            )
        
        # Persist to database
        PlayerMapper.persist_jersey_detections(db, job_id, aggregated)
        
        # Build response
        mappings = []
        confidence_counts = {
            'high': 0,
            'medium': 0,
            'low': 0,
            'no_match': 0,
        }
        
        for track_id, data in aggregated.items():
            suggested_player = data['suggested_player']
            match_rating = data['match_rating']
            
            if match_rating in confidence_counts:
                confidence_counts[match_rating] += 1
            
            mapping = PlayerMappingSuggestion(
                track_id=track_id,
                detected_jersey=data['detected_jersey'],
                frame_count=data['frame_count'],
                confidence_mean=data['confidence_mean'],
                confidence_max=data['confidence_max'],
                suggested_player_id=suggested_player.id if suggested_player else None,
                suggested_player_name=suggested_player.full_name if suggested_player else None,
                match_rating=match_rating,
            )
            mappings.append(mapping)
        
        # Sort by confidence descending
        mappings.sort(key=lambda m: (m.confidence_max, m.frame_count), reverse=True)
        
        return PlayerMappingResponse(
            job_id=job_id,
            team_id=team_id,
            total_mappings=len(mappings),
            high_confidence_count=confidence_counts['high'],
            medium_confidence_count=confidence_counts['medium'],
            low_confidence_count=confidence_counts['low'],
            no_match_count=confidence_counts['no_match'],
            mappings=mappings,
        )
    
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"Error mapping players for job {job_id}: {exc}")
        raise HTTPException(status_code=500, detail=f"Player mapping failed: {exc}")

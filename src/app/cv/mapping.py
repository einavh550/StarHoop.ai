"""
Player mapping service for associating detected jerseys to Player records.

Aggregates jersey detections from detection_frames and matches to team players.
"""

import logging
from collections import defaultdict
from statistics import mean

from sqlalchemy.orm import Session

from app.db.models import DetectionFrame, JerseyDetection, Player, VideoJob

logger = logging.getLogger(__name__)


class PlayerMapper:
    """
    Maps detected jersey numbers to Player records.
    
    Aggregates individual frame-level detections into per-track summaries
    with confidence metrics, then matches to known players on a team.
    """
    
    @staticmethod
    def aggregate_jerseys_from_video(
        db: Session,
        video_job_id: int,
        team_id: int,
    ) -> dict[int, dict]:
        """
        Aggregate jersey detections from all detection_frames for a video job.
        
        Groups by track_id, computes confidence statistics, and suggests player matches.
        
        Args:
            db: Database session
            video_job_id: ID of the VideoJob to process
            team_id: Team ID for player lookup
        
        Returns:
            Dict mapping track_id → {
                'detected_jersey': int,
                'frame_count': int,
                'confidence_mean': float,
                'confidence_max': float,
                'suggested_player': Player or None,
                'match_rating': str ('high', 'medium', 'low', 'no_match')
            }
        
        Raises:
            ValueError: If video_job not found or team_id mismatch
        """
        # Fetch the video job
        job = db.query(VideoJob).filter(VideoJob.id == video_job_id).first()
        if not job:
            raise ValueError(f"VideoJob {video_job_id} not found")
        
        if job.team_id != team_id:
            raise ValueError(f"VideoJob {video_job_id} belongs to team {job.team_id}, not {team_id}")
        
        # Fetch all detection frames
        detection_frames = db.query(DetectionFrame).filter(
            DetectionFrame.video_job_id == video_job_id
        ).all()
        
        if not detection_frames:
            logger.warning(f"No detection frames found for job {video_job_id}")
            return {}
        
        # Aggregate jerseys by track_id
        jersey_aggregates = defaultdict(lambda: {
            'confidences': [],
            'jersey_numbers': [],
        })
        
        for frame in detection_frames:
            detections = frame.detections_json or []
            for detection in detections:
                track_id = detection.get('track_id')
                jersey_num = detection.get('jersey_number')
                jersey_conf = detection.get('jersey_confidence', 0.0)
                
                # Only aggregate if detection has jersey data
                if track_id is not None and jersey_num is not None:
                    jersey_aggregates[track_id]['confidences'].append(jersey_conf)
                    jersey_aggregates[track_id]['jersey_numbers'].append(jersey_num)
        
        if not jersey_aggregates:
            logger.warning(f"No jersey detections found for job {video_job_id}")
            return {}
        
        # Compute statistics and match to players
        result = {}
        players_by_jersey = PlayerMapper._get_players_by_jersey(db, team_id)
        
        for track_id, stats in jersey_aggregates.items():
            confidences = stats['confidences']
            jersey_numbers = stats['jersey_numbers']
            
            # Most common jersey for this track
            detected_jersey = max(set(jersey_numbers), key=jersey_numbers.count)
            
            # Confidence metrics
            confidence_mean = mean(confidences)
            confidence_max = max(confidences)
            frame_count = len(confidences)
            
            # Find player match
            suggested_player = players_by_jersey.get(detected_jersey)
            
            # Rate match quality
            if suggested_player:
                match_rating = PlayerMapper._rate_match(confidence_mean, frame_count)
            else:
                match_rating = 'no_match'
            
            result[track_id] = {
                'detected_jersey': detected_jersey,
                'frame_count': frame_count,
                'confidence_mean': float(confidence_mean),
                'confidence_max': float(confidence_max),
                'suggested_player': suggested_player,
                'match_rating': match_rating,
            }
        
        return result
    
    @staticmethod
    def persist_jersey_detections(
        db: Session,
        video_job_id: int,
        aggregated_jerseys: dict[int, dict],
    ) -> list[JerseyDetection]:
        """
        Persist aggregated jersey detections to database.
        
        Creates or updates JerseyDetection records for bulk mapping queries.
        
        Args:
            db: Database session
            video_job_id: VideoJob ID
            aggregated_jerseys: Output from aggregate_jerseys_from_video()
        
        Returns:
            List of created JerseyDetection records
        """
        created = []
        
        for track_id, data in aggregated_jerseys.items():
            jersey_detection = JerseyDetection(
                video_job_id=video_job_id,
                track_id=track_id,
                detected_jersey_number=data['detected_jersey'],
                jersey_confidence=data['confidence_max'],  # Use max as primary confidence
                frame_count=data['frame_count'],
                confidence_mean=data['confidence_mean'],
                confidence_max=data['confidence_max'],
                mapped_player_id=data['suggested_player'].id if data['suggested_player'] else None,
            )
            db.add(jersey_detection)
            created.append(jersey_detection)
        
        db.commit()
        logger.info(f"Persisted {len(created)} jersey detections for job {video_job_id}")
        
        return created
    
    @staticmethod
    def _get_players_by_jersey(db: Session, team_id: int) -> dict[int, Player]:
        """
        Get mapping of jersey_number → Player for a team.
        
        Returns:
            Dict {jersey_number: Player}
        """
        players = db.query(Player).filter(Player.team_id == team_id).all()
        return {player.jersey_number: player for player in players}
    
    @staticmethod
    def _rate_match(confidence_mean: float, frame_count: int) -> str:
        """
        Rate match quality based on confidence and persistence.
        
        Args:
            confidence_mean: Average OCR confidence (0.0-1.0)
            frame_count: Number of frames detecting this jersey
        
        Returns:
            'high', 'medium', 'low', or 'no_match'
        """
        if confidence_mean >= 0.8 and frame_count >= 5:
            return 'high'
        elif confidence_mean >= 0.7 and frame_count >= 2:
            return 'medium'
        elif confidence_mean >= 0.6 or frame_count >= 3:
            return 'low'
        else:
            return 'no_match'


def extract_and_map_player_jerseys(
    db: Session,
    video_job_id: int,
    team_id: int,
) -> dict[int, dict]:
    """
    Convenience function: aggregate jerseys and persist to database.
    
    Returns the aggregation result for immediate API response.
    """
    aggregated = PlayerMapper.aggregate_jerseys_from_video(db, video_job_id, team_id)
    PlayerMapper.persist_jersey_detections(db, video_job_id, aggregated)
    return aggregated

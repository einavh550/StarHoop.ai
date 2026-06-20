"""
Player mapping service for associating detected jerseys to Player records.

Aggregates jersey detections from detection_frames and matches to team players.
Uses outlier-resistant aggregation and provides detailed diagnostics.
"""

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass
from statistics import mean, median, stdev
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import DetectionFrame, JerseyDetection, Player, VideoJob

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JerseyMatchDiagnostic:
    """Per-track match quality diagnostic for debugging."""
    track_id: int
    detected_jersey: int
    frame_count: int
    confidence_values: list[float]
    confidence_mean: float
    confidence_median: float
    confidence_std: float
    detected_jerseys_distinct: int
    detected_jerseys_list: list[int]
    suggested_player_id: Optional[int]
    suggested_player_name: Optional[str]
    match_rating: str
    match_reason: str


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
        
        Groups by track_id, computes confidence statistics using outlier-resistant methods,
        and suggests player matches. Provides detailed diagnostics per track.
        
        Args:
            db: Database session
            video_job_id: ID of the VideoJob to process
            team_id: Team ID for player lookup
        
        Returns:
            Dict mapping track_id → {
                'detected_jersey': int,
                'frame_count': int,
                'confidence_mean': float,
                'confidence_median': float,
                'confidence_std': float,
                'confidence_max': float,
                'suggested_player': Player or None,
                'match_rating': str ('high', 'medium', 'low', 'no_match'),
                'diagnostic': JerseyMatchDiagnostic
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
        
        # Aggregate jerseys by track_id with separate high-confidence tracking
        jersey_aggregates = defaultdict(lambda: {
            'confidences': [],
            'jersey_numbers': [],
            'high_confidence_votes': [],
            'team_ids': [],
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
                    # Track high-confidence detections separately for consensus voting
                    if jersey_conf >= settings.ocr_confidence_strict:
                        jersey_aggregates[track_id]['high_confidence_votes'].append(jersey_num)
                    # Remember the SigLIP team cluster for the single-team gate.
                    team_id = detection.get('team_id')
                    if team_id is not None:
                        jersey_aggregates[track_id]['team_ids'].append(int(team_id))
        
        if not jersey_aggregates:
            logger.warning(f"No jersey detections found for job {video_job_id}")
            return {}
        
        # Compute statistics and match to players
        result = {}
        players_by_jersey = PlayerMapper._get_players_by_jersey(db, team_id)
        
        for track_id, stats in jersey_aggregates.items():
            confidences = stats['confidences']
            jersey_numbers = stats['jersey_numbers']
            high_conf_jerseys = stats['high_confidence_votes']
            frame_count = len(confidences)
            
            # Statistical analysis
            confidence_mean = mean(confidences)
            confidence_max = max(confidences)
            confidence_median = median(confidences) if confidences else 0.0
            confidence_std = 0.0
            if len(confidences) > 1:
                try:
                    confidence_std = stdev(confidences)
                except Exception:
                    confidence_std = 0.0
            
            # Jersey selection: prefer high-confidence consensus if available
            if high_conf_jerseys:
                detected_jersey = max(set(high_conf_jerseys), key=high_conf_jerseys.count)
                selection_reason = "high_confidence_consensus"
            else:
                # Use outlier-resistant voting on all confidences
                detected_jersey = PlayerMapper._select_jersey_outlier_resistant(
                    jersey_numbers,
                    confidences,
                    confidence_median,
                )
                selection_reason = "outlier_resistant_voting"
            
            # Find player match
            suggested_player = players_by_jersey.get(detected_jersey)
            
            # Rate match quality with detailed reasoning
            match_rating, match_reason = PlayerMapper._rate_match_with_reason(
                confidence_mean=confidence_mean,
                confidence_median=confidence_median,
                confidence_std=confidence_std,
                frame_count=frame_count,
                player_exists=suggested_player is not None,
                selection_reason=selection_reason,
            )
            
            # Build diagnostic for troubleshooting
            diagnostic = JerseyMatchDiagnostic(
                track_id=int(track_id),
                detected_jersey=detected_jersey,
                frame_count=frame_count,
                confidence_values=sorted(confidences, reverse=True),
                confidence_mean=float(confidence_mean),
                confidence_median=float(confidence_median),
                confidence_std=float(confidence_std),
                detected_jerseys_distinct=len(set(jersey_numbers)),
                detected_jerseys_list=sorted(set(jersey_numbers)),
                suggested_player_id=suggested_player.id if suggested_player else None,
                suggested_player_name=suggested_player.full_name if suggested_player else None,
                match_rating=match_rating,
                match_reason=match_reason,
            )
            
            result[track_id] = {
                'detected_jersey': detected_jersey,
                'frame_count': frame_count,
                'confidence_mean': float(confidence_mean),
                'confidence_median': float(confidence_median),
                'confidence_std': float(confidence_std),
                'confidence_max': float(confidence_max),
                'suggested_player': suggested_player,
                'match_rating': match_rating,
                'diagnostic': diagnostic,
            }
            
            logger.info(
                f"track_id={track_id} jersey={detected_jersey} frames={frame_count} "
                f"conf_mean={confidence_mean:.3f} conf_std={confidence_std:.3f} "
                f"player={suggested_player.full_name if suggested_player else 'NONE'} "
                f"rating={match_rating} reason={match_reason}"
            )

        # Single-team opponent gate: only the SigLIP cluster that best matches the
        # coached roster keeps its player mappings; the other cluster's tracks map
        # to NULL so opponents are never forced onto your roster.
        if settings.opponent_team_gate:
            track_team = {
                track_id: Counter(stats['team_ids']).most_common(1)[0][0]
                for track_id, stats in jersey_aggregates.items()
                if stats['team_ids']
            }
            PlayerMapper.apply_opponent_gate(result, track_team)

        return result

    @staticmethod
    def select_coached_cluster(
        result: dict[int, dict],
        track_team: dict[int, int],
    ) -> Optional[int]:
        """Return the SigLIP cluster whose tracks best match the coached roster.

        Each cluster is scored by the total frame count of its roster-matched
        tracks (frame-weighted so track fragmentation does not skew the vote).
        The coached team is simply the cluster that looks most like the known
        roster. Returns ``None`` when no track matched any roster player.
        """
        score_per_cluster: dict[int, int] = defaultdict(int)
        for track_id, data in result.items():
            cluster = track_team.get(track_id)
            if cluster is None or data.get('suggested_player') is None:
                continue
            score_per_cluster[cluster] += int(data.get('frame_count', 1))
        if not score_per_cluster:
            return None
        return max(score_per_cluster, key=lambda cluster: score_per_cluster[cluster])

    @staticmethod
    def apply_opponent_gate(
        result: dict[int, dict],
        track_team: dict[int, int],
    ) -> dict[int, dict]:
        """Null out player mappings for tracks not on the coached team's cluster.

        Mutates and returns ``result``. A track is gated only when its cluster is
        known AND differs from the coached cluster; unknown-cluster tracks are
        left as-is so we never lose a genuine roster player to missing team data.
        """
        coached_cluster = PlayerMapper.select_coached_cluster(result, track_team)
        if coached_cluster is None:
            return result

        for track_id, data in result.items():
            cluster = track_team.get(track_id)
            if (
                cluster is not None
                and cluster != coached_cluster
                and data.get('suggested_player') is not None
            ):
                data['suggested_player'] = None
                data['match_rating'] = 'no_match'
                logger.info(
                    "opponent_gate: track_id=%s cluster=%s != coached %s -> mapped to NULL",
                    track_id,
                    cluster,
                    coached_cluster,
                )
        return result
    
    @staticmethod
    def _select_jersey_outlier_resistant(
        jersey_numbers: list[int],
        confidences: list[float],
        confidence_median: float,
    ) -> int:
        """
        Select the best jersey using outlier-resistant weighted voting.
        
        Gives higher weight to detections near the median confidence level,
        depressing the influence of extreme outliers (very high or very low confidence).
        
        Args:
            jersey_numbers: List of detected jersey numbers
            confidences: Corresponding confidence scores
            confidence_median: Median confidence value
        
        Returns:
            Selected jersey number
        """
        if not jersey_numbers:
            return 0
        
        # Compute weights: detections close to median get weight 1.0,
        # detections far from median (outliers) get reduced weight
        weights = {}
        for jersey, conf in zip(jersey_numbers, confidences):
            diff_from_median = abs(conf - confidence_median)
            # Outliers (>0.6 away from median) get 50% weight
            weight = 0.5 if diff_from_median > settings.jersey_aggregation_outlier_threshold else 1.0
            weights[jersey] = weights.get(jersey, 0) + weight
        
        # Pick jersey with strongest weighted support, breaking ties by frequency
        detected_jersey = max(weights.items(), key=lambda item: (item[1], jersey_numbers.count(item[0])))[0]
        return detected_jersey
    
    @staticmethod
    def _rate_match_with_reason(
        confidence_mean: float,
        confidence_median: float,
        confidence_std: float,
        frame_count: int,
        player_exists: bool,
        selection_reason: str,
    ) -> tuple[str, str]:
        """
        Rate match quality and provide detailed reasoning for the rating.
        
        Uses mean, median, and std dev for nuanced quality assessment.
        Higher consistency (low std dev) and persistence (high frame count)
        indicate better matches.
        
        Args:
            confidence_mean: Average OCR confidence
            confidence_median: Median OCR confidence
            confidence_std: Standard deviation of confidences
            frame_count: Number of frames detecting this jersey
            player_exists: Whether jersey found in roster
            selection_reason: How jersey was selected (for logging)
        
        Returns:
            (rating, reason) tuple where rating is 'high'|'medium'|'low'|'no_match'
        """
        if not player_exists:
            return 'no_match', 'jersey_not_in_roster'
        
        # High rating: consistent, high-confidence, persistent detections
        if confidence_mean >= 0.8 and frame_count >= 5 and confidence_std < 0.15:
            return 'high', 'high_consistency_and_persistence'
        
        # Medium rating: good mean confidence and reasonable persistence
        if confidence_mean >= 0.7 and frame_count >= 3:
            return 'medium', 'good_confidence_and_persistence'
        
        # Medium rating: strong median confidence even if mean is lower (outliers present)
        if confidence_median >= 0.75 and frame_count >= 3:
            return 'medium', 'high_median_confidence'
        
        # Low rating: minimum acceptable quality for matching
        if confidence_mean >= 0.6 or frame_count >= 4:
            return 'low', 'marginal_quality_confidence_or_persistence'
        
        return 'low', 'insufficient_confidence_or_frame_count'

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

        # Idempotency: clear any rows from a prior run before inserting, so
        # re-running the mapping (e.g. POST .../player_mapping/auto a second time)
        # never trips the UNIQUE(video_job_id, track_id) constraint. The annotated
        # export already does this; doing it here makes every caller safe.
        db.query(JerseyDetection).filter(
            JerseyDetection.video_job_id == video_job_id
        ).delete()
        db.flush()

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
    def consolidate_tracks_by_player(aggregated: dict[int, dict]) -> dict[int, int]:
        """Group tracks that resolve to the SAME roster player under one
        canonical track id (Fix 1 — track consolidation).

        SAM-2 frequently fragments one physical player into several
        ``track_id``s (chunk boundaries, occlusion loss, late re-prompts). Since
        every fragment carries the same jersey, they all map to the same
        ``suggested_player``. This returns ``{track_id: canonical_track_id}`` so
        downstream consumers can treat the fragments as one identity. The
        canonical track is the one with the most frames (tie-break: highest
        ``confidence_max``). Tracks with no matched player map to themselves and
        are never merged with anything.
        """
        by_player: dict[int, list[int]] = defaultdict(list)
        for track_id, data in aggregated.items():
            player = data.get("suggested_player")
            if player is None:
                continue
            by_player[player.id].append(int(track_id))

        canonical: dict[int, int] = {int(track_id): int(track_id) for track_id in aggregated}
        for tracks in by_player.values():
            best = max(
                tracks,
                key=lambda t: (aggregated[t]["frame_count"], aggregated[t]["confidence_max"]),
            )
            for track_id in tracks:
                canonical[track_id] = best
        return canonical

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
        Rate match quality based on confidence and persistence (backward compatible).
        
        Args:
            confidence_mean: Average OCR confidence (0.0-1.0)
            frame_count: Number of frames detecting this jersey
        
        Returns:
            'high', 'medium', 'low', or 'no_match'
        """
        rating, _ = PlayerMapper._rate_match_with_reason(
            confidence_mean=confidence_mean,
            confidence_median=confidence_mean,
            confidence_std=0.0,
            frame_count=frame_count,
            player_exists=True,
            selection_reason='legacy_compatibility',
        )
        return rating


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

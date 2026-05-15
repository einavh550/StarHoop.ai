"""
Jersey mapping diagnostics endpoint for Milestone 3 Phase 2.5 (quality assurance).

Provides visibility into mapping quality, confidence metrics, and per-track diagnostics.
Helps identify issues before rendering exports or sharing results.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.cv.mapping import JerseyMatchDiagnostic, PlayerMapper
from app.db.models import VideoJob
from app.db.session import get_db

router = APIRouter(prefix="/api/videos", tags=["mapping_diagnostics"])


class JerseyMatchDiagnosticResponse(BaseModel):
    """Diagnostic info for a single track's jersey mapping."""
    track_id: int
    detected_jersey: int
    frame_count: int
    confidence_values: list[float]
    confidence_mean: float
    confidence_median: float
    confidence_std: float
    detected_jerseys_distinct: int
    detected_jerseys_list: list[int]
    suggested_player_id: int | None = None
    suggested_player_name: str | None = None
    match_rating: str
    match_reason: str


class MappingQualityMetricsResponse(BaseModel):
    """Overall quality metrics for job mapping."""
    job_id: int
    team_id: int
    total_tracks: int
    high_confidence_tracks: int
    medium_confidence_tracks: int
    low_confidence_tracks: int
    no_match_tracks: int
    overall_quality_score: float  # 0.0 to 1.0
    quality_assessment: str  # 'excellent', 'good', 'fair', 'poor'
    diagnostics: list[JerseyMatchDiagnosticResponse] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


@router.get("/{job_id}/player_mapping/diagnostics", response_model=MappingQualityMetricsResponse)
def diagnose_mapping_quality(
    job_id: int,
    team_id: Annotated[int, Query(..., description="Team ID for verification")],
    include_diagnostics: bool = False,
    db: Session = Depends(get_db),
) -> MappingQualityMetricsResponse:
    """
    Diagnose jersey mapping quality for a completed video job.
    
    Provides comprehensive metrics including confidence statistics per track,
    overall quality assessment, and actionable recommendations.
    
    Args:
        job_id: VideoJob ID to diagnose
        team_id: Team ID for verification
        include_diagnostics: Include per-track diagnostic details (verbose)
        db: Database session
    
    Returns:
        MappingQualityMetricsResponse with quality metrics and diagnostics
    
    Raises:
        HTTPException 404: If video job not found
        HTTPException 400: If team_id doesn't match job.team_id
    """
    job = db.query(VideoJob).filter(VideoJob.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail=f"VideoJob {job_id} not found")
    
    if job.team_id != team_id:
        raise HTTPException(
            status_code=400,
            detail=f"VideoJob {job_id} belongs to team {job.team_id}, not {team_id}",
        )
    
    try:
        # Aggregate jerseys with diagnostics
        aggregated = PlayerMapper.aggregate_jerseys_from_video(db, job_id, team_id)
        
        if not aggregated:
            return MappingQualityMetricsResponse(
                job_id=job_id,
                team_id=team_id,
                total_tracks=0,
                high_confidence_tracks=0,
                medium_confidence_tracks=0,
                low_confidence_tracks=0,
                no_match_tracks=0,
                overall_quality_score=0.0,
                quality_assessment="no_data",
                diagnostics=[],
                recommendations=["No jersey detections found in video. Check video quality."],
            )
        
        # Count confidence levels
        high_count = 0
        medium_count = 0
        low_count = 0
        no_match_count = 0
        
        diagnostics_list: list[JerseyMatchDiagnosticResponse] = []
        confidence_means = []
        
        for track_id, data in aggregated.items():
            rating = data['match_rating']
            if rating == 'high':
                high_count += 1
            elif rating == 'medium':
                medium_count += 1
            elif rating == 'low':
                low_count += 1
            else:  # no_match
                no_match_count += 1
            
            diagnostic: JerseyMatchDiagnostic = data['diagnostic']
            diagnostic_response = JerseyMatchDiagnosticResponse(
                track_id=diagnostic.track_id,
                detected_jersey=diagnostic.detected_jersey,
                frame_count=diagnostic.frame_count,
                confidence_values=diagnostic.confidence_values,
                confidence_mean=diagnostic.confidence_mean,
                confidence_median=diagnostic.confidence_median,
                confidence_std=diagnostic.confidence_std,
                detected_jerseys_distinct=diagnostic.detected_jerseys_distinct,
                detected_jerseys_list=diagnostic.detected_jerseys_list,
                suggested_player_id=diagnostic.suggested_player_id,
                suggested_player_name=diagnostic.suggested_player_name,
                match_rating=diagnostic.match_rating,
                match_reason=diagnostic.match_reason,
            )
            diagnostics_list.append(diagnostic_response)
            confidence_means.append(diagnostic.confidence_mean)
        
        # Calculate overall quality score
        total = len(aggregated)
        quality_score = 0.0
        
        if total > 0:
            # Score based on distribution of confidence levels
            # High: 1.0 per track, Medium: 0.7 per track, Low: 0.4 per track, No match: 0.0
            score_value = (high_count * 1.0 + medium_count * 0.7 + low_count * 0.4) / total
            # Penalize high std dev (inconsistency)
            std_devs = [d.confidence_std for d in diagnostics_list]
            avg_std = sum(std_devs) / len(std_devs) if std_devs else 0.0
            std_penalty = min(0.2, avg_std * 0.5)  # Up to 20% penalty for high variance
            quality_score = max(0.0, score_value - std_penalty)
        
        # Determine assessment
        if quality_score >= 0.85:
            assessment = 'excellent'
        elif quality_score >= 0.70:
            assessment = 'good'
        elif quality_score >= 0.50:
            assessment = 'fair'
        else:
            assessment = 'poor'
        
        # Generate recommendations
        recommendations = []
        if no_match_count > 0:
            recommendations.append(
                f"{no_match_count} track(s) had jersey numbers not found in team roster. "
                "Check team roster configuration."
            )
        if low_count > total * 0.5:
            recommendations.append(
                f"Over 50% of tracks have low mapping confidence. "
                "Video quality or OCR settings may need adjustment."
            )
        if avg_std > 0.30:
            recommendations.append(
                "High variance in confidence across frames suggests inconsistent jersey detection. "
                "Consider video preprocessing or lighting improvements."
            )
        if quality_score >= 0.85:
            recommendations.append("Mapping quality is excellent. Ready for export and analysis.")
        elif quality_score >= 0.70:
            recommendations.append("Mapping quality is good. Export and results are reliable.")
        else:
            recommendations.append("Mapping quality is low. Consider retrying with recompute flag.")
        
        response_diagnostics = diagnostics_list if include_diagnostics else []
        
        return MappingQualityMetricsResponse(
            job_id=job_id,
            team_id=team_id,
            total_tracks=total,
            high_confidence_tracks=high_count,
            medium_confidence_tracks=medium_count,
            low_confidence_tracks=low_count,
            no_match_tracks=no_match_count,
            overall_quality_score=round(quality_score, 3),
            quality_assessment=assessment,
            diagnostics=response_diagnostics,
            recommendations=recommendations,
        )
    
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Diagnostics failed: {exc}") from exc

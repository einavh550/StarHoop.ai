"""
Unit tests for improved player mapping logic with outlier resistance.
Tests the top-grade jersey recognition improvements in Milestone 3 Phase 2.5.
"""

import pytest
from unittest.mock import Mock
from statistics import mean, median, stdev

from app.cv.mapping import PlayerMapper, JerseyMatchDiagnostic
from app.db.models import Player


class TestOutlierResistantJerseySelection:
    """Test jersey selection with outlier-resistant votin    POST http://localhost:8000/api/videos/upload
    team_id = 1 (Star Hoopers)
    file = your_basketball_video.mp4    $baseUrl = "http://localhost:8000"
    $teamId = 1
    $videoPath = "C:\Users\einav\OneDrive\Desktop\basketballVideo.mp4"
    $outputPath = "$env:USERPROFILE\Desktop\annotated_result.mp4"
    
    # 1. Upload video
    $uploadResponse = curl.exe -X POST "$baseUrl/api/videos/upload" `
      -F "team_id=$teamId" `
      -F "file=@$videoPath"
    
    $uploadJson = $uploadResponse | ConvertFrom-Json
    $jobId = $uploadJson.job_id
    $uploadJson
    
    # 2. Check processing status until it finishes
    do {
      Start-Sleep -Seconds 5
      $statusJson = curl.exe "$baseUrl/api/videos/$jobId" | ConvertFrom-Json
      $statusJson
    } while ($statusJson.status -eq "pending" -or $statusJson.status -eq "processing")
    
    # 3. Map detected jerseys to players
    $mappingJson = curl.exe -X POST "$baseUrl/api/videos/$jobId/player_mapping/auto?team_id=$teamId&recompute_from_frames=true" | ConvertFrom-Json
    $mappingJson
    
    # 4. Check mapping quality
    $diagnosticsJson = curl.exe "$baseUrl/api/videos/$jobId/player_mapping/diagnostics?team_id=$teamId&include_diagnostics=true" | ConvertFrom-Json
    $diagnosticsJson
    
    # 5. Create annotated export
    $exportJson = curl.exe -X POST "$baseUrl/api/videos/$jobId/exports/annotated" | ConvertFrom-Json
    $exportJson
    
    # 6. Download result video
    curl.exe "$baseUrl/api/videos/$jobId/exports/annotated/$($exportJson.export_id)/download" -o $outputPath    POST http://localhost:8000/api/videos/upload
    team_id = 1 (Star Hoopers)
    file = your_basketball_video.mp4g."""
    
    def test_select_jersey_all_high_confidence(self) -> None:
        """Test selection when all detections have high, consistent confidence."""
        jersey_numbers = [23, 23, 23, 23]
        confidences = [0.95, 0.93, 0.96, 0.94]
        median_conf = median(confidences)
        
        result = PlayerMapper._select_jersey_outlier_resistant(
            jersey_numbers, confidences, median_conf
        )
        
        assert result == 23
    
    def test_select_jersey_with_outlier_low_confidence(self) -> None:
        """Test selection ignores low-confidence outliers."""
        # 3 high-confidence detections of jersey 23, 1 low-confidence outlier
        jersey_numbers = [23, 23, 23, 24]
        confidences = [0.90, 0.91, 0.92, 0.25]  # Last one is outlier
        median_conf = median(confidences)  # Median will be around 0.80
        
        result = PlayerMapper._select_jersey_outlier_resistant(
            jersey_numbers, confidences, median_conf
        )
        
        # Should still pick jersey 23 despite outlier (weighted voting)
        assert result == 23
    
    def test_select_jersey_with_outlier_high_confidence(self) -> None:
        """Test selection resists high-confidence outliers."""
        # Mostly jersey 5, but one outlier jersey 23 with very high confidence
        jersey_numbers = [5, 5, 5, 23]
        confidences = [0.70, 0.72, 0.68, 0.99]  # Last is outlier
        median_conf = median(confidences)  # Around 0.70
        
        result = PlayerMapper._select_jersey_outlier_resistant(
            jersey_numbers, confidences, median_conf
        )
        
        # Should pick jersey 5 (consistent) over 23 (single outlier)
        assert result == 5
    
    def test_select_jersey_conflicting_jerseys(self) -> None:
        """Test selection with conflicting jersey detections."""
        jersey_numbers = [10, 10, 11, 11]
        confidences = [0.85, 0.82, 0.80, 0.81]
        median_conf = median(confidences)  # Around 0.81
        
        result = PlayerMapper._select_jersey_outlier_resistant(
            jersey_numbers, confidences, median_conf
        )
        
        # Either 10 or 11, both have equal 2 votes
        assert result in (10, 11)


class TestRateMatchWithReason:
    """Test match rating with detailed reasoning."""
    
    def test_rate_match_high_consistency(self) -> None:
        """Test high rating for consistent, persistent detections."""
        rating, reason = PlayerMapper._rate_match_with_reason(
            confidence_mean=0.85,
            confidence_median=0.86,
            confidence_std=0.05,
            frame_count=10,
            player_exists=True,
            selection_reason="high_confidence_consensus",
        )
        
        assert rating == 'high'
        assert 'consistency' in reason.lower() or 'high' in reason.lower()
    
    def test_rate_match_medium_good_confidence(self) -> None:
        """Test medium rating for good mean confidence."""
        rating, reason = PlayerMapper._rate_match_with_reason(
            confidence_mean=0.75,
            confidence_median=0.76,
            confidence_std=0.10,
            frame_count=5,
            player_exists=True,
            selection_reason="high_confidence_consensus",
        )
        
        assert rating == 'medium'
    
    def test_rate_match_medium_high_median(self) -> None:
        """Test medium rating when median is high despite lower mean (outliers)."""
        rating, reason = PlayerMapper._rate_match_with_reason(
            confidence_mean=0.62,
            confidence_median=0.80,  # Most detections are high
            confidence_std=0.25,  # High variance due to outliers
            frame_count=4,
            player_exists=True,
            selection_reason="outlier_resistant_voting",
        )
        
        assert rating == 'medium'
        assert 'median' in reason.lower()
    
    def test_rate_match_no_match_jersey_not_in_roster(self) -> None:
        """Test no_match when player doesn't exist."""
        rating, reason = PlayerMapper._rate_match_with_reason(
            confidence_mean=0.95,
            confidence_median=0.95,
            confidence_std=0.01,
            frame_count=20,
            player_exists=False,  # Key: player not in roster
            selection_reason="high_confidence_consensus",
        )
        
        assert rating == 'no_match'
        assert 'roster' in reason.lower()
    
    def test_rate_match_low_insufficient_quality(self) -> None:
        """Test low rating for marginal quality."""
        rating, reason = PlayerMapper._rate_match_with_reason(
            confidence_mean=0.55,
            confidence_median=0.58,
            confidence_std=0.15,
            frame_count=2,
            player_exists=True,
            selection_reason="outlier_resistant_voting",
        )
        
        assert rating == 'low'


class TestDiagnosticDataclass:
    """Test diagnostic info generation."""
    
    def test_diagnostic_creation(self) -> None:
        """Test building diagnostic for a track."""
        diag = JerseyMatchDiagnostic(
            track_id=7,
            detected_jersey=23,
            frame_count=10,
            confidence_values=[0.95, 0.92, 0.88],
            confidence_mean=0.916,
            confidence_median=0.92,
            confidence_std=0.033,
            detected_jerseys_distinct=1,
            detected_jerseys_list=[23],
            suggested_player_id=5,
            suggested_player_name="John Doe",
            match_rating="high",
            match_reason="high_consistency_and_persistence",
        )
        
        assert diag.track_id == 7
        assert diag.detected_jersey == 23
        assert diag.frame_count == 10
        assert diag.suggested_player_name == "John Doe"
        assert diag.match_rating == "high"


class TestBackwardCompatibility:
    """Test backward compatibility with legacy rating method."""
    
    def test_legacy_rate_match_high(self) -> None:
        """Test old _rate_match still works."""
        rating = PlayerMapper._rate_match(confidence_mean=0.85, frame_count=10)
        assert rating == 'high'
    
    def test_legacy_rate_match_medium(self) -> None:
        """Test legacy method for medium rating."""
        rating = PlayerMapper._rate_match(confidence_mean=0.72, frame_count=3)
        assert rating == 'medium'
    
    def test_legacy_rate_match_low(self) -> None:
        """Test legacy method for low rating."""
        rating = PlayerMapper._rate_match(confidence_mean=0.55, frame_count=1)
        assert rating == 'low'

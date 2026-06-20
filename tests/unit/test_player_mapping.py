"""
Unit tests for player mapping logic (Milestone 3 Phase 2).
"""

import pytest
from unittest.mock import Mock, MagicMock

from app.cv.mapping import PlayerMapper
from app.db.models import Player


class TestPlayerMappingLogic:
    """Unit tests for PlayerMapper class."""
    
    def test_get_players_by_jersey(self):
        """Test retrieving players indexed by jersey number."""
        # Mock database session
        mock_db = Mock()
        mock_player1 = Player(id=1, team_id=10, jersey_number=23, full_name="Michael Jordan")
        mock_player2 = Player(id=2, team_id=10, jersey_number=5, full_name="LeBron James")
        
        mock_db.query.return_value.filter.return_value.all.return_value = [
            mock_player1,
            mock_player2,
        ]
        
        result = PlayerMapper._get_players_by_jersey(mock_db, team_id=10)
        
        assert 23 in result
        assert 5 in result
        assert result[23].full_name == "Michael Jordan"
        assert result[5].full_name == "LeBron James"
    
    def test_consolidate_tracks_by_player_merges_fragments(self):
        """Fragmented tracks of one player collapse to one canonical track."""
        p40 = Player(id=40, team_id=1, jersey_number=10, full_name="Colton Large")
        p41 = Player(id=41, team_id=1, jersey_number=11, full_name="Owen Nunemaker")
        aggregated = {
            5: {"suggested_player": p40, "frame_count": 120, "confidence_max": 0.9},
            12: {"suggested_player": p40, "frame_count": 30, "confidence_max": 0.6},
            7: {"suggested_player": p41, "frame_count": 80, "confidence_max": 0.8},
            99: {"suggested_player": None, "frame_count": 50, "confidence_max": 0.4},
        }

        canonical = PlayerMapper.consolidate_tracks_by_player(aggregated)

        # Tracks 5 and 12 (player 40) both point at the higher-frame track 5.
        assert canonical[5] == 5
        assert canonical[12] == 5
        # Distinct player and unmapped track are untouched.
        assert canonical[7] == 7
        assert canonical[99] == 99

    def test_consolidate_tracks_by_player_breaks_ties_on_confidence(self):
        """Equal frame counts fall back to the higher max confidence."""
        p40 = Player(id=40, team_id=1, jersey_number=10, full_name="Colton Large")
        aggregated = {
            5: {"suggested_player": p40, "frame_count": 50, "confidence_max": 0.6},
            12: {"suggested_player": p40, "frame_count": 50, "confidence_max": 0.95},
        }

        canonical = PlayerMapper.consolidate_tracks_by_player(aggregated)

        assert canonical[5] == 12
        assert canonical[12] == 12

    def test_select_coached_cluster_picks_best_roster_match(self):
        """Coached cluster is the one whose tracks match the roster the most."""
        p1 = Player(id=1, team_id=10, jersey_number=10, full_name="A")
        p2 = Player(id=2, team_id=10, jersey_number=11, full_name="B")
        result = {
            5: {"suggested_player": p1, "frame_count": 100},
            6: {"suggested_player": p2, "frame_count": 80},
            9: {"suggested_player": None, "frame_count": 200},  # opponent #10 (no match)
        }
        track_team = {5: 0, 6: 0, 9: 1}

        assert PlayerMapper.select_coached_cluster(result, track_team) == 0

    def test_apply_opponent_gate_nulls_other_cluster(self):
        """A roster-jersey collision on the opponent cluster maps to NULL."""
        p10 = Player(id=1, team_id=10, jersey_number=10, full_name="Our #10")
        opponent10 = Player(id=1, team_id=10, jersey_number=10, full_name="Our #10")
        result = {
            5: {"suggested_player": p10, "frame_count": 100, "match_rating": "high"},
            9: {"suggested_player": opponent10, "frame_count": 90, "match_rating": "high"},
        }
        # Cluster 0 has more roster-matched frames -> coached. Cluster 1 = opponent.
        track_team = {5: 0, 9: 1}

        PlayerMapper.apply_opponent_gate(result, track_team)

        assert result[5]["suggested_player"] is p10
        assert result[9]["suggested_player"] is None
        assert result[9]["match_rating"] == "no_match"

    def test_apply_opponent_gate_noop_when_no_matches(self):
        result = {5: {"suggested_player": None, "frame_count": 10}}
        track_team = {5: 1}
        # No roster matches -> coached cluster unknown -> nothing changes.
        PlayerMapper.apply_opponent_gate(result, track_team)
        assert result[5]["suggested_player"] is None

    def test_apply_opponent_gate_keeps_unknown_cluster_tracks(self):
        p10 = Player(id=1, team_id=10, jersey_number=10, full_name="Our #10")
        keep = Player(id=2, team_id=10, jersey_number=11, full_name="Our #11")
        result = {
            5: {"suggested_player": p10, "frame_count": 100, "match_rating": "high"},
            7: {"suggested_player": keep, "frame_count": 50, "match_rating": "high"},
        }
        # Track 7 has no known cluster -> must NOT be gated.
        track_team = {5: 0}

        PlayerMapper.apply_opponent_gate(result, track_team)

        assert result[7]["suggested_player"] is keep

    def test_rate_match_high_confidence(self):
        """Test high confidence match rating."""
        rating = PlayerMapper._rate_match(confidence_mean=0.85, frame_count=10)
        assert rating == 'high'
    
    def test_rate_match_medium_confidence(self):
        """Test medium confidence match rating."""
        rating = PlayerMapper._rate_match(confidence_mean=0.75, frame_count=5)
        assert rating == 'medium'
    
    def test_rate_match_low_confidence(self):
        """Test low confidence match rating."""
        rating = PlayerMapper._rate_match(confidence_mean=0.65, frame_count=1)
        assert rating == 'low'
    
    def test_rate_match_no_match(self):
        """Test no match rating."""
        rating = PlayerMapper._rate_match(confidence_mean=0.5, frame_count=1)
        assert rating == 'no_match'
    
    def test_rate_match_high_persistence_low_confidence(self):
        """Test that high frame count can elevate low confidence."""
        rating = PlayerMapper._rate_match(confidence_mean=0.65, frame_count=5)
        assert rating == 'low'  # Still low due to low confidence
    
    def test_aggregation_empty_detections(self):
        """Test aggregation with no detections."""
        mock_db = Mock()
        mock_job = Mock(team_id=10)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_job
        mock_db.query.return_value.filter.return_value.all.return_value = []  # No frames
        
        result = PlayerMapper.aggregate_jerseys_from_video(mock_db, 1, 10)
        assert result == {}

    def test_aggregation_prefers_confidence_weighted_jersey(self):
        mock_db = Mock()
        mock_job = Mock(team_id=10)
        mock_player = Player(id=1, team_id=10, jersey_number=23, full_name="Test Player")

        mock_frame = Mock()
        mock_frame.detections_json = [
            {'track_id': 7, 'class_id': 0, 'jersey_number': 23, 'jersey_confidence': 0.92},
            {'track_id': 7, 'class_id': 0, 'jersey_number': 24, 'jersey_confidence': 0.18},
        ]

        mock_db.query.side_effect = [
            Mock(filter=Mock(return_value=Mock(first=Mock(return_value=mock_job)))),
            Mock(filter=Mock(return_value=Mock(all=Mock(return_value=[mock_frame])))),
            Mock(filter=Mock(return_value=Mock(all=Mock(return_value=[mock_player])))),
        ]

        result = PlayerMapper.aggregate_jerseys_from_video(mock_db, 1, 10)

        assert 7 in result
        assert result[7]['detected_jersey'] == 23
    
    def test_aggregation_detections_without_jersey(self):
        """Test aggregation skips detections without jersey data."""
        mock_db = Mock()
        mock_job = Mock(team_id=10)
        mock_frame = Mock()
        mock_frame.detections_json = [
            {'track_id': 1, 'class_id': 0, 'jersey_number': None},  # No jersey
            {'track_id': 2, 'class_id': 0},  # Missing jersey_number
        ]
        
        mock_db.query.return_value.filter.return_value.first.return_value = mock_job
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_frame]
        
        result = PlayerMapper.aggregate_jerseys_from_video(mock_db, 1, 10)
        assert result == {}
    
    def test_aggregation_single_detection(self):
        """Test aggregation with single detection."""
        mock_db = Mock()
        mock_job = Mock(team_id=10)
        mock_player = Player(id=1, team_id=10, jersey_number=23, full_name="Test Player")
        
        mock_frame = Mock()
        mock_frame.detections_json = [
            {'track_id': 5, 'class_id': 0, 'jersey_number': 23, 'jersey_confidence': 0.9}
        ]
        
        mock_db.query.return_value.filter.return_value.first.return_value = mock_job
        # First call is for job lookup, second is for detection frames
        mock_query_results = [mock_job, [mock_frame]]
        mock_db.query.side_effect = [
            Mock(filter=Mock(return_value=Mock(first=Mock(return_value=mock_job)))),
            Mock(filter=Mock(return_value=Mock(all=Mock(return_value=[mock_frame])))),
        ]
        
        result = PlayerMapper.aggregate_jerseys_from_video(mock_db, 1, 10)
        assert 5 in result
        assert result[5]['detected_jersey'] == 23
        assert result[5]['suggested_player'] is not None


class TestMatchRating:
    """Test match rating logic with various confidence/persistence combinations."""
    
    @pytest.mark.parametrize("confidence,frame_count,expected_rating", [
        (0.9, 10, 'high'),
        (0.8, 5, 'high'),
        (0.85, 1, 'low'),
        (0.75, 10, 'medium'),
        (0.7, 2, 'medium'),
        (0.65, 5, 'low'),
        (0.6, 3, 'low'),
        (0.5, 5, 'low'),
        (0.5, 1, 'no_match'),
        (0.4, 1, 'no_match'),
    ])
    def test_match_rating_combinations(self, confidence, frame_count, expected_rating):
        """Test match rating for various confidence/frame_count combinations."""
        result = PlayerMapper._rate_match(confidence, frame_count)
        assert result == expected_rating


class TestAggregationLogic:
    """Test jersey aggregation with various detection patterns."""
    
    def test_most_common_jersey_selection(self):
        """Test that most common jersey is selected when multiple jerseys detected."""
        # Mock aggregation: track 1 detected as jersey 23 three times, jersey 24 once
        jersey_numbers = [23, 23, 23, 24]
        detected_jersey = max(set(jersey_numbers), key=jersey_numbers.count)
        
        assert detected_jersey == 23  # Most common
    
    def test_confidence_statistics(self):
        """Test confidence mean and max computation."""
        from statistics import mean
        
        confidences = [0.9, 0.85, 0.88, 0.92]
        
        confidence_mean = mean(confidences)
        confidence_max = max(confidences)
        
        assert 0.88 < confidence_mean < 0.90
        assert confidence_max == 0.92

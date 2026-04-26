"""
Integration tests for player mapping API endpoint (Milestone 3 Phase 2).

Tests end-to-end: creating detection data → mapping → API response.
"""

import json
import pytest
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.db.base import Base
from app.db.models import Coach, Team, Player, VideoJob, DetectionFrame
from app.cv.mapping import PlayerMapper


@pytest.fixture
def test_data_setup():
    """Set up test database with coaches, teams, and players."""
    # Create in-memory SQLite database
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    # Create test data
    coach = Coach(full_name="Coach Test", email="coach@example.com")
    session.add(coach)
    session.flush()
    
    team = Team(coach_id=coach.id, name="Test Team", season="2025-2026", logo_url=None)
    session.add(team)
    session.flush()
    
    # Add players with known jerseys
    player_23 = Player(team_id=team.id, full_name="Player 23", jersey_number=23)
    player_5 = Player(team_id=team.id, full_name="Player 5", jersey_number=5)
    player_32 = Player(team_id=team.id, full_name="Player 32", jersey_number=32)
    
    session.add_all([player_23, player_5, player_32])
    session.flush()
    
    # Create video job
    job = VideoJob(
        team_id=team.id,
        status="completed",
        source_filename="test_video.mp4",
        storage_path="/uploads/test_video.mp4",
        total_frames=100,
        processed_frames=100,
    )
    session.add(job)
    session.flush()
    
    session.commit()
    
    yield {
        'session': session,
        'engine': engine,
        'coach': coach,
        'team': team,
        'job': job,
        'players': {
            23: player_23,
            5: player_5,
            32: player_32,
        }
    }
    
    session.close()


def test_aggregation_with_mock_detections(test_data_setup):
    """Test jersey aggregation with realistic detection data."""
    session = test_data_setup['session']
    job = test_data_setup['job']
    team = test_data_setup['team']
    
    # Create detection frames with jersey OCR data
    # Track 1: Jersey 23 with high confidence (5 frames)
    for frame_num in range(5):
        detections_json = [
            {
                'track_id': 1,
                'class_id': 0,
                'class_name': 'person',
                'confidence': 0.9,
                'jersey_number': 23,
                'jersey_confidence': 0.85 + (frame_num * 0.01),  # Gradually increasing
                'bbox': {'x1': 100, 'y1': 50, 'x2': 200, 'y2': 300}
            }
        ]
        frame = DetectionFrame(
            video_job_id=job.id,
            frame_number=frame_num,
            timestamp_sec=Decimal(str(frame_num * 0.033)),
            detections_json=detections_json,
        )
        session.add(frame)
    
    # Track 2: Jersey 5 with medium confidence (3 frames)
    for frame_num in range(5, 8):
        detections_json = [
            {
                'track_id': 2,
                'class_id': 0,
                'class_name': 'person',
                'confidence': 0.88,
                'jersey_number': 5,
                'jersey_confidence': 0.75,
                'bbox': {'x1': 300, 'y1': 100, 'x2': 400, 'y2': 350}
            }
        ]
        frame = DetectionFrame(
            video_job_id=job.id,
            frame_number=frame_num,
            timestamp_sec=Decimal(str(frame_num * 0.033)),
            detections_json=detections_json,
        )
        session.add(frame)
    
    # Track 3: Jersey 32 not in roster (1 frame)
    detections_json = [
        {
            'track_id': 3,
            'class_id': 0,
            'class_name': 'person',
            'confidence': 0.92,
            'jersey_number': 97,  # Not in team roster
            'jersey_confidence': 0.88,
            'bbox': {'x1': 500, 'y1': 200, 'x2': 600, 'y2': 400}
        }
    ]
    frame = DetectionFrame(
        video_job_id=job.id,
        frame_number=8,
        timestamp_sec=Decimal('0.264'),
        detections_json=detections_json,
    )
    session.add(frame)
    
    session.commit()
    
    # Test aggregation
    aggregated = PlayerMapper.aggregate_jerseys_from_video(session, job.id, team.id)
    
    # Validate results
    assert len(aggregated) == 3  # Three track IDs
    
    # Track 1: Jersey 23 (high confidence)
    assert 1 in aggregated
    track_1 = aggregated[1]
    assert track_1['detected_jersey'] == 23
    assert track_1['frame_count'] == 5
    assert track_1['confidence_mean'] > 0.88
    assert track_1['confidence_max'] > 0.89
    assert track_1['suggested_player'] is not None
    assert track_1['suggested_player'].jersey_number == 23
    assert track_1['match_rating'] == 'high'
    
    # Track 2: Jersey 5 (medium confidence)
    assert 2 in aggregated
    track_2 = aggregated[2]
    assert track_2['detected_jersey'] == 5
    assert track_2['frame_count'] == 3
    assert track_2['confidence_mean'] == 0.75
    assert track_2['suggested_player'].jersey_number == 5
    assert track_2['match_rating'] == 'medium'
    
    # Track 3: Jersey 97 (not in roster)
    assert 3 in aggregated
    track_3 = aggregated[3]
    assert track_3['detected_jersey'] == 97
    assert track_3['suggested_player'] is None
    assert track_3['match_rating'] == 'no_match'


def test_jersey_detection_persistence(test_data_setup):
    """Test persisting aggregated jerseys to jersey_detections table."""
    session = test_data_setup['session']
    job = test_data_setup['job']
    team = test_data_setup['team']
    
    # Create sample detection
    detections_json = [
        {
            'track_id': 10,
            'class_id': 0,
            'jersey_number': 23,
            'jersey_confidence': 0.9,
        }
    ]
    frame = DetectionFrame(
        video_job_id=job.id,
        frame_number=0,
        timestamp_sec=Decimal('0.0'),
        detections_json=detections_json,
    )
    session.add(frame)
    session.commit()
    
    # Aggregate and persist
    aggregated = PlayerMapper.aggregate_jerseys_from_video(session, job.id, team.id)
    created = PlayerMapper.persist_jersey_detections(session, job.id, aggregated)
    
    # Verify persistence
    assert len(created) == 1
    jersey_detection = created[0]
    assert jersey_detection.video_job_id == job.id
    assert jersey_detection.track_id == 10
    assert jersey_detection.detected_jersey_number == 23
    assert jersey_detection.mapped_player_id is not None


def test_aggregation_with_mixed_jersey_consistency(test_data_setup):
    """Test track with same player detected as different jersey (OCR variance)."""
    session = test_data_setup['session']
    job = test_data_setup['job']
    team = test_data_setup['team']
    
    # Track 1: Detected as jersey 23 four times, jersey 24 once (OCR error)
    # Should select 23 as most common
    detections_all = [
        [
            {'track_id': 1, 'class_id': 0, 'jersey_number': 23, 'jersey_confidence': 0.88}
        ],
        [
            {'track_id': 1, 'class_id': 0, 'jersey_number': 23, 'jersey_confidence': 0.87}
        ],
        [
            {'track_id': 1, 'class_id': 0, 'jersey_number': 24, 'jersey_confidence': 0.65}  # Error
        ],
        [
            {'track_id': 1, 'class_id': 0, 'jersey_number': 23, 'jersey_confidence': 0.89}
        ],
        [
            {'track_id': 1, 'class_id': 0, 'jersey_number': 23, 'jersey_confidence': 0.90}
        ],
    ]
    
    for frame_num, detections_json in enumerate(detections_all):
        frame = DetectionFrame(
            video_job_id=job.id,
            frame_number=frame_num,
            timestamp_sec=Decimal(str(frame_num * 0.033)),
            detections_json=detections_json,
        )
        session.add(frame)
    
    session.commit()
    
    aggregated = PlayerMapper.aggregate_jerseys_from_video(session, job.id, team.id)
    
    # Should select jersey 23 (most common)
    assert aggregated[1]['detected_jersey'] == 23
    assert aggregated[1]['frame_count'] == 5  # All frames considered for stats
    assert 0.78 < aggregated[1]['confidence_mean'] < 0.88
    assert aggregated[1]['confidence_max'] == 0.90


def test_aggregation_empty_video_job(test_data_setup):
    """Test aggregation on video with no detections."""
    session = test_data_setup['session']
    team = test_data_setup['team']
    
    # Create new empty job
    empty_job = VideoJob(
        team_id=team.id,
        status="completed",
        source_filename="empty.mp4",
        storage_path="/uploads/empty.mp4",
    )
    session.add(empty_job)
    session.commit()
    
    # Aggregate empty job
    aggregated = PlayerMapper.aggregate_jerseys_from_video(session, empty_job.id, team.id)
    
    assert aggregated == {}

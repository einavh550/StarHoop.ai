"""
Integration test for Milestone 3 Phase 1: Jersey OCR in detection_frames.
Tests that jersey_number and jersey_confidence are persisted in detection JSON.
"""

import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.db.models.detection_frame import DetectionFrame


@pytest.fixture
def db_session():
    """Fixture: Get session from existing database (must be running)."""
    # This test assumes a running PostgreSQL instance in Docker
    db_url = "postgresql://postgres:password@localhost/hoopstar"
    engine = create_engine(db_url)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


class TestJerseyOCRIntegration:
    """Integration tests for jersey OCR data persistence."""
    
    def test_detection_frames_have_jersey_fields(self, db_session):
        """Test that jersey_number and jersey_confidence are in detection JSON."""
        # Query any detection frame from the database
        detections = db_session.query(DetectionFrame).limit(1).all()
        
        # If no detections exist yet, skip (test will pass after first video processed)
        if not detections:
            pytest.skip("No detections in database yet; run video processing first")
        
        detection_frame = detections[0]
        assert detection_frame.detections_json is not None
        
        # Parse JSON payload
        if isinstance(detection_frame.detections_json, str):
            payload = json.loads(detection_frame.detections_json)
        else:
            payload = detection_frame.detections_json
        
        # Verify payload is a list
        assert isinstance(payload, list), "detections_json should be a list of detection objects"
        
        if len(payload) > 0:
            # Check first detection has M3 Phase 1 fields
            first_detection = payload[0]
            
            # M2 fields (should always be present)
            assert "class_id" in first_detection
            assert "class_name" in first_detection
            assert "confidence" in first_detection
            assert "track_id" in first_detection
            assert "bbox" in first_detection
            
            # M3 Phase 1 fields (new, must be present)
            assert "jersey_number" in first_detection, "jersey_number field missing (M3 P1 not integrated)"
            assert "jersey_confidence" in first_detection, "jersey_confidence field missing (M3 P1 not integrated)"
            
            # Validate field types
            jersey_number = first_detection["jersey_number"]
            jersey_confidence = first_detection["jersey_confidence"]
            
            assert jersey_number is None or isinstance(jersey_number, int), \
                f"jersey_number should be int or None, got {type(jersey_number)}"
            assert isinstance(jersey_confidence, float), \
                f"jersey_confidence should be float, got {type(jersey_confidence)}"
            
            # If jersey was detected, confidence should be > 0
            if jersey_number is not None:
                assert jersey_confidence > 0.0, \
                    f"jersey_confidence should be > 0 when jersey_number is detected, got {jersey_confidence}"
    
    def test_detection_schema_backward_compatibility(self, db_session):
        """Test that M2 fields are still present after M3 P1 integration."""
        detections = db_session.query(DetectionFrame).limit(1).all()
        
        if not detections:
            pytest.skip("No detections in database yet")
        
        detection_frame = detections[0]
        
        if isinstance(detection_frame.detections_json, str):
            payload = json.loads(detection_frame.detections_json)
        else:
            payload = detection_frame.detections_json
        
        if len(payload) > 0:
            first_detection = payload[0]
            
            # All M2 fields should still be present
            required_fields = ["class_id", "class_name", "confidence", "bbox", "track_id"]
            for field in required_fields:
                assert field in first_detection, f"M2 field '{field}' missing; backward compatibility broken"


# Note: These tests are integration tests that require:
# 1. PostgreSQL running via Docker Compose
# 2. At least one video processed through the pipeline
# To run: pytest tests/integration/test_m3_phase1_ocr.py -v -s

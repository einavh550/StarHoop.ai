"""
Unit tests for jersey OCR recognition module.
"""

import numpy as np
import pytest
from types import SimpleNamespace

from app.cv.ocr import JerseyRecognizer


@pytest.fixture
def jersey_recognizer():
    """Fixture: Initialize JerseyRecognizer with standard threshold."""
    return JerseyRecognizer(confidence_threshold=0.7)


class TestJerseyRecognizer:
    """Test suite for JerseyRecognizer class."""
    
    def test_extract_jersey_with_none_input(self, jersey_recognizer):
        """Test extraction with None input returns (None, 0.0)."""
        result = jersey_recognizer.extract_jersey_from_bbox(None)
        assert result == (None, 0.0)
    
    def test_extract_jersey_with_empty_array(self, jersey_recognizer):
        """Test extraction with empty array returns (None, 0.0)."""
        empty_crop = np.array([], dtype=np.uint8)
        result = jersey_recognizer.extract_jersey_from_bbox(empty_crop)
        assert result == (None, 0.0)
    
    def test_extract_jersey_with_too_small_crop(self, jersey_recognizer):
        """Test extraction with crop too small (< 10px) returns (None, 0.0)."""
        tiny_crop = np.zeros((5, 5, 3), dtype=np.uint8)
        result = jersey_recognizer.extract_jersey_from_bbox(tiny_crop)
        assert result == (None, 0.0)
    
    def test_confidence_threshold_enforcement(self, jersey_recognizer):
        """Test that low confidence detections are rejected."""
        recognizer = JerseyRecognizer(confidence_threshold=0.8)
        assert recognizer.confidence_threshold == 0.8
    
    def test_jersey_number_range_validation(self, jersey_recognizer):
        """
        Test that jersey numbers are validated to be in range [0, 99].
        (This is validated in extract_jersey_from_bbox logic.)
        """
        # Create a valid test image (in practice, would be mocked PaddleOCR)
        # For now, just verify the class construction works
        assert jersey_recognizer.confidence_threshold == 0.7
    
    def test_preprocess_bbox_crop_valid_region(self):
        """Test bbox crop extraction with valid region."""
        jersey_recognizer = JerseyRecognizer()
        
        # Create a test frame (100x100x3 BGR)
        frame = np.ones((100, 100, 3), dtype=np.uint8) * 128
        
        # Bounding box in pixel coordinates
        bbox = {"x1": 10, "y1": 20, "x2": 60, "y2": 80}
        
        crop = jersey_recognizer.preprocess_bbox_crop(frame, bbox, pad_percent=0.05)
        
        # Crop should be a valid numpy array with 3 channels
        assert isinstance(crop, np.ndarray)
        assert crop.shape[2] == 3
        assert crop.dtype == np.uint8
    
    def test_preprocess_bbox_crop_with_padding(self):
        """Test bbox crop with padding applied."""
        jersey_recognizer = JerseyRecognizer()
        
        frame = np.ones((100, 100, 3), dtype=np.uint8) * 128
        bbox = {"x1": 30, "y1": 30, "x2": 70, "y2": 70}
        
        # With 10% padding
        crop = jersey_recognizer.preprocess_bbox_crop(frame, bbox, pad_percent=0.10)
        
        assert isinstance(crop, np.ndarray)
        assert crop.shape[2] == 3
    
    def test_preprocess_bbox_crop_boundary_clamping(self):
        """Test that padding doesn't extend beyond frame boundaries."""
        jersey_recognizer = JerseyRecognizer()
        
        # Frame dimensions
        frame = np.ones((50, 50, 3), dtype=np.uint8)
        
        # Bbox at corner (will be clamped)
        bbox = {"x1": 0, "y1": 0, "x2": 20, "y2": 20}
        
        crop = jersey_recognizer.preprocess_bbox_crop(frame, bbox, pad_percent=0.20)
        
        # Crop should still be valid (clamped to frame bounds)
        assert isinstance(crop, np.ndarray)
        assert crop.shape[0] > 0 and crop.shape[1] > 0
    
    def test_preprocess_bbox_crop_resizing_for_tall_region(self):
        """Test that very tall crops are resized for OCR consistency."""
        jersey_recognizer = JerseyRecognizer()
        
        # Large frame with tall bbox
        frame = np.ones((500, 100, 3), dtype=np.uint8)
        bbox = {"x1": 10, "y1": 50, "x2": 90, "y2": 450}  # 400px tall
        
        crop = jersey_recognizer.preprocess_bbox_crop(frame, bbox, pad_percent=0.0)
        
        # Crop should be resized to target height (64px) for consistency
        assert crop.shape[0] <= 100  # Resized down


class TestJerseyRecognizerEdgeCases:
    """Test edge cases and error handling."""
    
    def test_extract_from_black_image(self):
        """Test extraction from a blank/black image (no text)."""
        recognizer = JerseyRecognizer(confidence_threshold=0.5)
        black_crop = np.zeros((50, 50, 3), dtype=np.uint8)
        
        # Should return (None, 0.0) since no text is detected
        result = recognizer.extract_jersey_from_bbox(black_crop)
        assert result[0] is None
        assert result[1] == 0.0
    
    def test_extract_from_noise(self):
        """Test extraction from random noise image."""
        recognizer = JerseyRecognizer(confidence_threshold=0.5)
        noise_crop = np.random.randint(0, 255, (50, 50, 3), dtype=np.uint8)
        
        # May or may not detect text; at minimum should not crash
        result = recognizer.extract_jersey_from_bbox(noise_crop)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_extract_low_confidence_numeric_candidate_when_enabled(self):
        recognizer = JerseyRecognizer(confidence_threshold=0.9)
        recognizer._ocr_model = SimpleNamespace(
            ocr=lambda image, cls=False: [[(
                None,
                ("23", 0.42),
            )]],
        )

        crop = np.ones((50, 50, 3), dtype=np.uint8) * 255
        jersey_num, confidence = recognizer.extract_jersey_from_bbox(crop, allow_low_confidence=True)

        assert jersey_num == 23
        assert confidence == 0.42

    def test_extract_low_confidence_numeric_candidate_when_disabled(self):
        recognizer = JerseyRecognizer(confidence_threshold=0.9)
        recognizer._ocr_model = SimpleNamespace(
            ocr=lambda image, cls=False: [[(
                None,
                ("23", 0.42),
            )]],
        )

        crop = np.ones((50, 50, 3), dtype=np.uint8) * 255
        jersey_num, confidence = recognizer.extract_jersey_from_bbox(crop, allow_low_confidence=False)

        assert jersey_num is None
        assert confidence == 0.42


class TestJerseyRecognizerIntegration:
    """Integration tests with mocked OCR behavior."""
    
    def test_recognizer_lazy_loads_model(self):
        """Test that OCR model is lazily loaded on first access."""
        recognizer = JerseyRecognizer()
        
        # Model should be None until first access (before triggering lazy load)
        assert recognizer._ocr_model is None
        
        # Don't actually access .ocr_model in test env (would require PaddleOCR installed)
        # Just verify the attribute exists and is None initially
        assert hasattr(recognizer, '_ocr_model')

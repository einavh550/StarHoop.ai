"""
Jersey number OCR module for basketball player detection.

Uses PaddleOCR to extract jersey numbers from player bounding box crops.
Provides confidence scores and handles edge cases (non-numeric results, low confidence).
"""

import logging
import re
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class JerseyRecognizer:
    """
    Extracts jersey numbers from player bounding box crops using PaddleOCR.
    
    Attributes:
        confidence_threshold: Minimum OCR confidence (0.0-1.0) to accept a digit result.
        ocr_model: Lazy-loaded PaddleOCR model instance.
    """
    
    def __init__(self, confidence_threshold: float = 0.7) -> None:
        """
        Initialize JerseyRecognizer.
        
        Args:
            confidence_threshold: Minimum OCR confidence for valid digit extraction. Default 0.7.
        """
        self.confidence_threshold = confidence_threshold
        self._ocr_model: Optional["PaddleOCR"] = None  # type: ignore
    
    @property
    def ocr_model(self):
        """Lazy-load PaddleOCR model on first access."""
        if self._ocr_model is None:
            try:
                from paddleocr import PaddleOCR  # pyright: ignore[reportMissingImports]
                self._ocr_model = PaddleOCR(use_angle_cls=False, lang='en')
                logger.info("PaddleOCR model loaded successfully.")
            except ImportError as exc:
                raise RuntimeError(
                    "paddleocr is not installed. Install requirements.txt dependencies first."
                ) from exc
        return self._ocr_model
    
    def extract_jersey_from_bbox(self, image_crop: np.ndarray) -> tuple[Optional[int], float]:
        """
        Extract jersey number from a player bounding box crop.
        
        Args:
            image_crop: 3-channel BGR numpy array containing just the player region.
        
        Returns:
            Tuple of (jersey_number or None, confidence). 
            - If successful and confidence >= threshold: (int, float >= threshold)
            - If no valid digits found or confidence < threshold: (None, 0.0)
            - If image is invalid or OCR fails: (None, 0.0)
        
        Examples:
            jersey_num, conf = recognizer.extract_jersey_from_bbox(crop)
            # jersey_num=23, conf=0.85 (valid)
            # jersey_num=None, conf=0.0 (invalid or low confidence)
        """
        if image_crop is None or image_crop.size == 0:
            return None, 0.0
        
        if image_crop.shape[0] < 10 or image_crop.shape[1] < 10:
            # Crop too small for reliable OCR
            return None, 0.0
        
        try:
            # Run PaddleOCR on the bbox crop
            results = self.ocr_model.ocr(image_crop, cls=False)
            
            if not results or not results[0]:
                # No text detected
                return None, 0.0
            
            # Extract all detected text blocks and their confidences
            text_blocks = []
            for line in results:
                for text_tuple in line:
                    bbox_coords, (text, ocr_confidence) = text_tuple
                    text_blocks.append((text.strip(), ocr_confidence))
            
            if not text_blocks:
                return None, 0.0
            
            # Sort by confidence (highest first) and try to extract digits
            text_blocks.sort(key=lambda x: x[1], reverse=True)
            
            for detected_text, ocr_confidence in text_blocks:
                # Extract digits only (handle "23", "05", "3", etc.)
                digits = re.findall(r'\d+', detected_text)
                
                if digits:
                    # Found digit(s); treat "05" as 5, "23" as 23
                    jersey_num = int(digits[0])
                    
                    # Validate: jersey numbers are typically 0-99
                    if 0 <= jersey_num <= 99:
                        if ocr_confidence >= self.confidence_threshold:
                            logger.debug(
                                f"Jersey extracted: {jersey_num}, confidence: {ocr_confidence:.2f}"
                            )
                            return jersey_num, float(ocr_confidence)
                        else:
                            logger.debug(
                                f"Jersey candidate '{jersey_num}' rejected: confidence {ocr_confidence:.2f} < {self.confidence_threshold}"
                            )
                            return None, float(ocr_confidence)
            
            # No valid digits found
            return None, 0.0
        
        except Exception as exc:
            logger.warning(f"OCR extraction failed: {exc}", exc_info=True)
            return None, 0.0
    
    def preprocess_bbox_crop(
        self, 
        frame: np.ndarray, 
        bbox: dict,  # {"x1": float, "y1": float, "x2": float, "y2": float}
        pad_percent: float = 0.05
    ) -> np.ndarray:
        """
        Extract and preprocess a bounding box crop from a frame.
        
        Applies optional padding and resizing to improve OCR performance.
        
        Args:
            frame: Full frame (BGR numpy array).
            bbox: Bounding box dict with keys x1, y1, x2, y2 (normalized or pixel coords).
            pad_percent: Padding as fraction of bbox size (default 5%).
        
        Returns:
            Cropped and preprocessed 3-channel BGR image.
        """
        h, w = frame.shape[:2]
        
        # Assume bbox is in pixel coordinates (not normalized)
        x1, y1, x2, y2 = int(bbox['x1']), int(bbox['y1']), int(bbox['x2']), int(bbox['y2'])
        
        # Add padding
        pad_x = int((x2 - x1) * pad_percent)
        pad_y = int((y2 - y1) * pad_percent)
        
        x1 = max(0, x1 - pad_x)
        y1 = max(0, y1 - pad_y)
        x2 = min(w, x2 + pad_x)
        y2 = min(h, y2 + pad_y)
        
        crop = frame[y1:y2, x1:x2]
        
        if crop.size == 0:
            return np.zeros((10, 10, 3), dtype=np.uint8)
        
        # Optionally resize to standard height for consistency (e.g., 64px height)
        # This can improve OCR accuracy on very small or very large regions
        crop_h, crop_w = crop.shape[:2]
        if crop_h < 20 or crop_h > 200:
            target_height = 64
            scale = target_height / crop_h
            new_w = int(crop_w * scale)
            crop = cv2.resize(crop, (new_w, target_height), interpolation=cv2.INTER_LINEAR)
        
        return crop

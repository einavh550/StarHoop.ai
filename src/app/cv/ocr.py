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

from app.core.config import settings

logger = logging.getLogger(__name__)


class JerseyRecognizer:
    """Extract jersey numbers from player bounding box crops using PaddleOCR."""

    def __init__(self, confidence_threshold: float = 0.7) -> None:
        self.confidence_threshold = confidence_threshold
        self._ocr_model: Optional["PaddleOCR"] = None  # type: ignore
        self._last_ocr_reason: str = "not_run"

    @property
    def last_ocr_reason(self) -> str:
        return self._last_ocr_reason

    def _set_last_ocr_reason(self, reason: str) -> None:
        self._last_ocr_reason = reason

    @property
    def ocr_model(self):
        if self._ocr_model is None:
            try:
                from paddleocr import PaddleOCR  # pyright: ignore[reportMissingImports]

                self._ocr_model = PaddleOCR(use_angle_cls=False, lang="en")
                logger.info("PaddleOCR model loaded successfully.")
            except ImportError as exc:
                raise RuntimeError(
                    "paddleocr is not installed. Install requirements.txt dependencies first."
                ) from exc
        return self._ocr_model

    def preprocess_bbox_crop(
        self,
        frame: np.ndarray,
        bbox: dict,
        pad_percent: float = 0.05,
        target_height: int = 64,
    ) -> np.ndarray:
        h, w = frame.shape[:2]

        x1, y1, x2, y2 = int(bbox["x1"]), int(bbox["y1"]), int(bbox["x2"]), int(bbox["y2"])

        pad_x = int((x2 - x1) * pad_percent)
        pad_y = int((y2 - y1) * pad_percent)

        x1 = max(0, x1 - pad_x)
        y1 = max(0, y1 - pad_y)
        x2 = min(w, x2 + pad_x)
        y2 = min(h, y2 + pad_y)

        crop = frame[y1:y2, x1:x2]
        logger.debug(
            "OCR crop bbox=%s padded_bbox=(%s,%s,%s,%s) frame_size=%sx%s crop_size=%sx%s",
            bbox,
            x1,
            y1,
            x2,
            y2,
            w,
            h,
            crop.shape[1] if crop.size else 0,
            crop.shape[0] if crop.size else 0,
        )

        if crop.size == 0:
            self._set_last_ocr_reason("empty_crop")
            return np.zeros((10, 10, 3), dtype=np.uint8)

        crop_h, crop_w = crop.shape[:2]
        if crop_h < settings.ocr_min_crop_size_px or crop_w < settings.ocr_min_crop_size_px:
            self._set_last_ocr_reason("crop_too_small")
            return np.zeros((10, 10, 3), dtype=np.uint8)

        if crop_h != target_height:
            scale = target_height / float(crop_h)
            new_w = max(1, int(round(crop_w * scale)))
            logger.debug("Resizing OCR crop from %sx%s to %sx%s", crop_w, crop_h, new_w, target_height)
            crop = cv2.resize(crop, (new_w, target_height), interpolation=cv2.INTER_CUBIC)

        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        blurred = cv2.GaussianBlur(enhanced, (3, 3), 0)
        sharpen_kernel = np.array(
            [[-1, -1, -1],
             [-1,  9, -1],
             [-1, -1, -1]],
            dtype=np.float32,
        )
        sharpened = cv2.filter2D(blurred, -1, sharpen_kernel)
        return cv2.cvtColor(sharpened, cv2.COLOR_GRAY2BGR)

    def _build_ocr_variants(self, image_crop: np.ndarray) -> list[tuple[str, np.ndarray]]:
        gray = cv2.cvtColor(image_crop, cv2.COLOR_BGR2GRAY)
        _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        inverted = cv2.bitwise_not(otsu)
        adaptive = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            11,
        )

        return [
            ("base", image_crop),
            ("otsu", cv2.cvtColor(otsu, cv2.COLOR_GRAY2BGR)),
            ("inverted_otsu", cv2.cvtColor(inverted, cv2.COLOR_GRAY2BGR)),
            ("adaptive", cv2.cvtColor(adaptive, cv2.COLOR_GRAY2BGR)),
        ]

    @staticmethod
    def _parse_ocr_results(results) -> list[tuple[str, float]]:
        text_blocks: list[tuple[str, float]] = []
        for line in results or []:
            for text_tuple in line or []:
                _, (text, ocr_confidence) = text_tuple
                text_blocks.append((text.strip(), float(ocr_confidence)))

        text_blocks.sort(key=lambda item: item[1], reverse=True)
        return text_blocks

    def extract_jersey_from_bbox(
        self,
        image_crop: np.ndarray,
        allow_low_confidence: bool = False,
    ) -> tuple[Optional[int], float]:
        self._set_last_ocr_reason("not_run")

        if image_crop is None or image_crop.size == 0:
            self._set_last_ocr_reason("empty_crop")
            return None, 0.0

        if image_crop.shape[0] < 10 or image_crop.shape[1] < 10:
            logger.debug("OCR crop too small: %sx%s", image_crop.shape[1], image_crop.shape[0])
            self._set_last_ocr_reason("crop_too_small")
            return None, 0.0

        try:
            best_numeric_candidate: tuple[int, float] | None = None
            best_candidate_reason = "no_valid_digits"

            for variant_name, variant in self._build_ocr_variants(image_crop):
                results = self.ocr_model.ocr(variant, cls=False)
                text_blocks = self._parse_ocr_results(results)

                if not text_blocks:
                    logger.debug("OCR variant '%s' returned no text blocks", variant_name)
                    continue

                for detected_text, ocr_confidence in text_blocks:
                    digits = re.findall(r"\d+", detected_text)
                    if not digits:
                        continue

                    jersey_num = int(digits[0])
                    if not 0 <= jersey_num <= 99:
                        continue

                    if ocr_confidence >= self.confidence_threshold:
                        self._set_last_ocr_reason(f"accepted:{variant_name}")
                        logger.debug(
                            "Jersey extracted: %s, confidence: %.2f, variant=%s",
                            jersey_num,
                            ocr_confidence,
                            variant_name,
                        )
                        return jersey_num, ocr_confidence

                    if best_numeric_candidate is None or ocr_confidence > best_numeric_candidate[1]:
                        best_numeric_candidate = (jersey_num, ocr_confidence)
                        best_candidate_reason = f"low_confidence:{variant_name}"
                    break

            if best_numeric_candidate is not None:
                jersey_num, ocr_confidence = best_numeric_candidate
                self._set_last_ocr_reason(best_candidate_reason)

                if allow_low_confidence:
                    logger.debug(
                        "Jersey candidate '%s' kept at low confidence: %.2f < %.2f",
                        jersey_num,
                        ocr_confidence,
                        self.confidence_threshold,
                    )
                    return jersey_num, ocr_confidence

                logger.debug(
                    "Jersey candidate '%s' rejected: confidence %.2f < %.2f",
                    jersey_num,
                    ocr_confidence,
                    self.confidence_threshold,
                )
                return None, ocr_confidence

            self._set_last_ocr_reason("no_text_or_digits")
            logger.debug("OCR text contained no valid jersey digits")
            return None, 0.0
        except Exception as exc:
            self._set_last_ocr_reason(f"ocr_failure:{exc.__class__.__name__}")
            logger.warning("OCR extraction failed: %s", exc, exc_info=True)
            return None, 0.0

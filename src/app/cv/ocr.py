"""
Jersey number OCR module for basketball player detection.

Uses PaddleOCR to extract jersey numbers from player bounding box crops.
Provides confidence scores and handles edge cases (non-numeric results, low confidence).
"""

import logging
import multiprocessing
import queue
import re
import threading
import time
from typing import Optional

import cv2
import numpy as np

from app.core.config import settings

logger = logging.getLogger(__name__)

_OCR_WORKER_TIMEOUT_SEC = 3.0
_OCR_WORKER_COOLDOWN_SEC = 60.0


def _ocr_worker(request_queue, response_queue, confidence_threshold: float) -> None:
    recognizer = JerseyRecognizer(confidence_threshold=confidence_threshold)
    while True:
        message = request_queue.get()
        if message is None:
            return

        request_id, image_crop, allow_low_confidence = message
        try:
            jersey_num, jersey_conf = recognizer.extract_jersey_from_bbox(
                image_crop,
                allow_low_confidence=allow_low_confidence,
            )
            response_queue.put(
                (request_id, jersey_num, jersey_conf, recognizer.last_ocr_reason, None)
            )
        except Exception as exc:
            response_queue.put(
                (request_id, None, 0.0, recognizer.last_ocr_reason, f"{exc.__class__.__name__}")
            )


class _OcrWorkerManager:
    def __init__(self, confidence_threshold: float) -> None:
        self._confidence_threshold = confidence_threshold
        self._context = multiprocessing.get_context("spawn")
        self._request_queue = None
        self._response_queue = None
        self._process = None
        self._lock = threading.Lock()
        self._next_request_id = 0
        self._failure_count = 0
        self._disabled_until = 0.0

    def _start_worker(self) -> None:
        self._request_queue = self._context.Queue(maxsize=10)
        self._response_queue = self._context.Queue(maxsize=10)
        self._process = self._context.Process(
            target=_ocr_worker,
            args=(self._request_queue, self._response_queue, self._confidence_threshold),
            daemon=True,
        )
        self._process.start()
        logger.info("Started OCR worker process pid=%s", self._process.pid)

    def _ensure_worker(self) -> bool:
        if time.monotonic() < self._disabled_until:
            return False
        if self._process is None or not self._process.is_alive():
            self._start_worker()
        return self._process is not None and self._process.is_alive()

    def request(self, image_crop: np.ndarray, allow_low_confidence: bool) -> tuple[Optional[int], float, str, Optional[str]]:
        with self._lock:
            if not self._ensure_worker():
                return None, 0.0, "ocr_worker_unavailable", "worker_not_running"

            request_id = self._next_request_id
            self._next_request_id += 1

            try:
                self._request_queue.put((request_id, image_crop, allow_low_confidence))
            except Exception as exc:
                return None, 0.0, "ocr_worker_unavailable", f"queue_put:{exc.__class__.__name__}"

            deadline = time.monotonic() + _OCR_WORKER_TIMEOUT_SEC
            while time.monotonic() < deadline:
                if self._process is not None and not self._process.is_alive():
                    self._failure_count += 1
                    self._disabled_until = time.monotonic() + _OCR_WORKER_COOLDOWN_SEC
                    return None, 0.0, "ocr_worker_crashed", "worker_exit"
                try:
                    response = self._response_queue.get(timeout=0.2)
                except queue.Empty:
                    continue

                response_id, jersey_num, jersey_conf, reason, error = response
                if response_id != request_id:
                    continue

                if error:
                    return None, 0.0, reason or "ocr_worker_error", error

                return jersey_num, float(jersey_conf), reason or "not_run", None

            self._failure_count += 1
            self._disabled_until = time.monotonic() + _OCR_WORKER_COOLDOWN_SEC
            return None, 0.0, "ocr_timeout", "timeout"


class IsolatedJerseyRecognizer:
    """Runs PaddleOCR in a subprocess to prevent native crashes from stopping the API."""

    def __init__(self, confidence_threshold: float = 0.7) -> None:
        self.confidence_threshold = confidence_threshold
        self._worker = _OcrWorkerManager(confidence_threshold)
        self._last_ocr_reason: str = "not_run"

    @property
    def last_ocr_reason(self) -> str:
        return self._last_ocr_reason

    def _set_last_ocr_reason(self, reason: str) -> None:
        self._last_ocr_reason = reason

    def preprocess_bbox_crop(
        self,
        frame: np.ndarray,
        bbox: dict,
        pad_percent: float = 0.05,
        target_height: int = 64,
    ) -> np.ndarray:
        recognizer = JerseyRecognizer(confidence_threshold=self.confidence_threshold)
        return recognizer.preprocess_bbox_crop(frame, bbox, pad_percent, target_height)

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

        jersey_num, jersey_conf, reason, error = self._worker.request(image_crop, allow_low_confidence)
        if error:
            logger.warning("OCR worker failure: %s", error)
        self._set_last_ocr_reason(reason)
        return jersey_num, jersey_conf


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
        """Parse PaddleOCR results. Handles both old and new result formats."""
        text_blocks: list[tuple[str, float]] = []

        for result_item in results or []:
            # New PaddleOCR format: dictionary with rec_texts and rec_scores
            if isinstance(result_item, dict):
                rec_texts = result_item.get("rec_texts", [])
                rec_scores = result_item.get("rec_scores", [])
                if rec_texts and rec_scores:
                    for text, score in zip(rec_texts, rec_scores):
                        if text and score is not None:
                            text_blocks.append((str(text).strip(), float(score)))
            # Old PaddleOCR format: nested list structure
            elif isinstance(result_item, (list, tuple)):
                for item in result_item or []:
                    text = None
                    ocr_confidence = None
                    if isinstance(item, (list, tuple)):
                        if len(item) >= 3 and isinstance(item[1], str):
                            text = item[1]
                            ocr_confidence = item[2]
                        elif len(item) >= 2 and isinstance(item[1], (list, tuple)) and len(item[1]) >= 2:
                            text = item[1][0]
                            ocr_confidence = item[1][1]
                    if text is not None and ocr_confidence is not None:
                        text_blocks.append((str(text).strip(), float(ocr_confidence)))

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
                try:
                    results = self.ocr_model.ocr(variant)
                    text_blocks = self._parse_ocr_results(results)
                except Exception as ocr_variant_error:
                    logger.warning("OCR variant '%s' failed: %s", variant_name, ocr_variant_error)
                    continue

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

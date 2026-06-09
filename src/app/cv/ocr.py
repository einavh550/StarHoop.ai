"""OCR helpers for jersey recognition.

This module serves two OCR integration surfaces used in the codebase:

* ``JerseyRecognizer``: the lightweight crop-based OCR helper covered by the
  existing unit tests.
* ``recognize_jersey_numbers``: a contract-safe adapter around the deployed
  Roboflow SmolVLM model used by the Modal CV pipeline.

The second surface exists because the current ``inference-gpu`` SmolVLM adapter
does not accept ``predict(image, prompt=...)`` directly. It requires either the
high-level ``prompt(...)`` method or the lower-level
``preprocess -> predict -> postprocess`` flow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


def _normalize_jersey_text(text: Any) -> str | None:
    """Extract a plausible jersey number string from free-form OCR output."""
    if text is None:
        return None

    digits = "".join(ch for ch in str(text).strip() if ch.isdigit())
    if not digits or len(digits) > 2:
        return None
    return digits


def _first_response_text(result: Any) -> str | None:
    """Best-effort extraction of generated text from SmolVLM responses."""
    if result is None:
        return None

    if isinstance(result, str):
        return result

    if isinstance(result, dict):
        for key in ("response", "text", "parsed_output"):
            value = result.get(key)
            if value is not None:
                return str(value)
        return None

    response = getattr(result, "response", None)
    if response is not None:
        return str(response)

    parsed_output = getattr(result, "parsed_output", None)
    if parsed_output is not None:
        return str(parsed_output)

    if isinstance(result, (list, tuple)) and result:
        return _first_response_text(result[0])

    return None


def recognize_jersey_number(ocr_model: Any, crop: np.ndarray, prompt: str) -> str | None:
    """Return a normalized jersey number string for one crop, or ``None``.

    The function is intentionally tolerant at the crop level: malformed model
    outputs or per-crop OCR failures return ``None`` instead of aborting the
    whole video job.
    """
    if crop is None or not isinstance(crop, np.ndarray) or crop.size == 0:
        return None

    try:
        if hasattr(ocr_model, "prompt"):
            result = ocr_model.prompt(images=crop, prompt=prompt)
            return _normalize_jersey_text(_first_response_text(result))

        if all(hasattr(ocr_model, attr) for attr in ("preprocess", "predict", "postprocess")):
            prepared = ocr_model.preprocess(crop, prompt=prompt)
            if not isinstance(prepared, tuple) or len(prepared) != 2:
                return None
            inputs, metadata = prepared
            predictions = ocr_model.predict(inputs)
            postprocessed = ocr_model.postprocess(predictions, metadata)
            return _normalize_jersey_text(_first_response_text(postprocessed))
    except Exception:
        return None

    return None


def recognize_jersey_numbers(ocr_model: Any, crops: list[np.ndarray], prompt: str) -> list[str | None]:
    """Recognize jersey numbers for many crops without failing the whole frame."""
    return [recognize_jersey_number(ocr_model, crop, prompt) for crop in crops]


@dataclass
class _NumericCandidate:
    value: int
    confidence: float
    accepted: bool
    reason: str


class JerseyRecognizer:
    """Crop-based jersey OCR helper used by the legacy/unit-tested path."""

    def __init__(self, confidence_threshold: float = 0.7) -> None:
        self.confidence_threshold = confidence_threshold
        self._ocr_model: Any | None = None
        self.last_ocr_reason = "not-run"

    @property
    def ocr_model(self) -> Any:
        if self._ocr_model is None:
            from paddleocr import PaddleOCR  # pyright: ignore[reportMissingImports]

            self._ocr_model = PaddleOCR(use_angle_cls=False, lang="en", show_log=False)
        return self._ocr_model

    def preprocess_bbox_crop(
        self,
        frame: np.ndarray,
        bbox: dict[str, float],
        *,
        pad_percent: float = 0.05,
        target_height: int = 64,
    ) -> np.ndarray:
        import cv2  # pyright: ignore[reportMissingImports]

        h, w = frame.shape[:2]
        x1, y1, x2, y2 = (int(bbox[k]) for k in ("x1", "y1", "x2", "y2"))
        pad_x = int(max(0, x2 - x1) * pad_percent)
        pad_y = int(max(0, y2 - y1) * pad_percent)

        x1 = max(0, x1 - pad_x)
        y1 = max(0, y1 - pad_y)
        x2 = min(w, x2 + pad_x)
        y2 = min(h, y2 + pad_y)

        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return np.array([], dtype=np.uint8)

        crop_h, crop_w = crop.shape[:2]
        if crop_h > target_height:
            resized_w = max(1, int(round(crop_w * (target_height / crop_h))))
            crop = cv2.resize(crop, (resized_w, target_height), interpolation=cv2.INTER_AREA)

        return crop

    def extract_jersey_from_bbox(
        self,
        crop: np.ndarray | None,
        *,
        allow_low_confidence: bool = False,
    ) -> tuple[int | None, float]:
        if crop is None or not isinstance(crop, np.ndarray) or crop.size == 0:
            self.last_ocr_reason = "empty-crop"
            return (None, 0.0)

        if crop.ndim < 2 or min(crop.shape[:2]) < 10:
            self.last_ocr_reason = "crop-too-small"
            return (None, 0.0)

        model = self._ocr_model
        if model is None:
            self.last_ocr_reason = "ocr-unavailable"
            return (None, 0.0)

        best_candidate: _NumericCandidate | None = None
        for variant in self._iter_crop_variants(crop):
            try:
                raw = model.ocr(variant, cls=False)
            except Exception:
                continue

            candidate = self._pick_numeric_candidate(raw, allow_low_confidence=allow_low_confidence)
            if candidate is None:
                continue

            best_candidate = candidate
            if candidate.accepted:
                self.last_ocr_reason = candidate.reason
                return (candidate.value, candidate.confidence)

        if best_candidate is not None:
            self.last_ocr_reason = best_candidate.reason
            return (best_candidate.value if best_candidate.accepted else None, best_candidate.confidence)

        self.last_ocr_reason = "no-numeric-candidate"
        return (None, 0.0)

    def _iter_crop_variants(self, crop: np.ndarray) -> list[np.ndarray]:
        variants = [crop]
        gray = None
        if crop.ndim == 3 and crop.shape[2] == 3:
            import cv2  # pyright: ignore[reportMissingImports]

            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            variants.append(gray)
        return variants

    def _pick_numeric_candidate(
        self,
        raw_result: Any,
        *,
        allow_low_confidence: bool,
    ) -> _NumericCandidate | None:
        best_value: int | None = None
        best_confidence = 0.0

        for line in raw_result or []:
            for entry in line or []:
                if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                    continue
                text_and_conf = entry[1]
                if not isinstance(text_and_conf, (list, tuple)) or len(text_and_conf) < 2:
                    continue
                text, confidence = text_and_conf[0], float(text_and_conf[1])
                normalized = _normalize_jersey_text(text)
                if normalized is None:
                    continue
                value = int(normalized)
                if value < 0 or value > 99:
                    continue
                if confidence > best_confidence:
                    best_value = value
                    best_confidence = confidence

        if best_value is None:
            return None

        accepted = allow_low_confidence or best_confidence >= self.confidence_threshold
        reason = (
            f"accepted:{best_value}@{best_confidence:.2f}"
            if accepted
            else f"below-threshold:{best_value}@{best_confidence:.2f}"
        )
        return _NumericCandidate(
            value=best_value,
            confidence=best_confidence,
            accepted=accepted,
            reason=reason,
        )
"""Video processing pipeline: frames in, structured detection batches out.

This is the de-Colab-ified engine. It runs the same five stages as the notebook
(RF-DETR detect -> SAM-2 prompt/propagate -> SigLIP team classify -> SmolVLM2
jersey OCR -> roster name lookup) but instead of rendering an annotated video it
yields ``ColabDetectionBatch`` objects matching ``schemas.py`` exactly.

``process_video`` is a generator: it yields one batch every ``batch_size``
processed frames and a final batch with ``final_batch=True`` at the end, so a
30-minute game streams results progressively instead of building one giant
object in memory.

All Jupyter/Colab specifics (``google.colab``, ``!pip``, ``IPython.display``,
``cv2_imshow``, ``sv.plot_image``) are intentionally absent.
"""

from __future__ import annotations

from typing import Any, Iterator

import numpy as np

from app.cv.models import (
    CLASS_ID_TO_NAME,
    NUMBER_CLASS_ID,
    NUMBER_RECOGNITION_MODEL_PROMPT,
    PLAYER_CLASS_IDS,
    PLAYER_DETECTION_MODEL_CONFIDENCE,
    PLAYER_DETECTION_MODEL_IOU_THRESHOLD,
    TEAM_NAMES,
    roster_name,
)
from app.cv.ocr import recognize_jersey_numbers
from app.cv.schemas import (
    ColabBoundingBox,
    ColabDetection,
    ColabDetectionBatch,
    ColabFramePayload,
)


class SAM2Tracker:
    """Stateful SAM-2 real-time tracker (ported verbatim from the Colab).

    Prompt once with RF-DETR boxes on the first frame, then ``propagate`` every
    subsequent frame to get stable ``tracker_id`` + masks. Stateful per video, so
    use a fresh instance (or ``reset``) for each clip.
    """

    def __init__(self, predictor: Any) -> None:
        self.predictor = predictor
        self._prompted = False

    def prompt_first_frame(self, frame: np.ndarray, detections: Any) -> None:
        import torch

        if len(detections) == 0:
            raise ValueError("detections must contain at least one box")

        if detections.tracker_id is None:
            detections.tracker_id = list(range(1, len(detections) + 1))

        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
            self.predictor.load_first_frame(frame)
            for xyxy, obj_id in zip(detections.xyxy, detections.tracker_id):
                bbox = np.asarray([xyxy], dtype=np.float32)
                self.predictor.add_new_prompt(frame_idx=0, obj_id=int(obj_id), bbox=bbox)

        self._prompted = True

    def propagate(self, frame: np.ndarray) -> Any:
        import torch
        import supervision as sv

        if not self._prompted:
            raise RuntimeError("Call prompt_first_frame before propagate")

        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
            tracker_ids, mask_logits = self.predictor.track(frame)

        tracker_ids = np.asarray(tracker_ids, dtype=np.int32)
        masks = (mask_logits > 0.0).cpu().numpy()
        masks = np.squeeze(masks).astype(bool)

        if masks.ndim == 2:
            masks = masks[None, ...]

        masks = np.array(
            [
                sv.filter_segments_by_distance(mask, relative_distance=0.03, mode="edge")
                for mask in masks
            ]
        )

        xyxy = sv.mask_to_xyxy(masks=masks)
        return sv.Detections(xyxy=xyxy, mask=masks, tracker_id=tracker_ids)

    def reset(self) -> None:
        self._prompted = False


def _detect_players(detector: Any, frame: np.ndarray) -> Any:
    """RF-DETR detect, keep only player-ish classes."""
    import supervision as sv

    result = detector.infer(
        frame,
        confidence=PLAYER_DETECTION_MODEL_CONFIDENCE,
        iou_threshold=PLAYER_DETECTION_MODEL_IOU_THRESHOLD,
    )[0]
    detections = sv.Detections.from_inference(result)
    return detections[np.isin(detections.class_id, PLAYER_CLASS_IDS)]


def _central_crops(frame: np.ndarray, detections: Any) -> list[np.ndarray]:
    """Central 40% crops used to feed the team classifier (jersey emphasis)."""
    import supervision as sv

    boxes = sv.scale_boxes(xyxy=detections.xyxy, factor=0.4)
    return [sv.crop_image(frame, box) for box in boxes]


def _coords_above_threshold(matrix: np.ndarray, threshold: float) -> list[tuple[int, int]]:
    """Return (row, col) index pairs where value > threshold, best first."""
    a = np.asarray(matrix)
    if a.size == 0:
        return []
    rows, cols = np.where(a > threshold)
    pairs = list(zip(rows.tolist(), cols.tolist()))
    pairs.sort(key=lambda rc: a[rc[0], rc[1]], reverse=True)
    return pairs


def _fit_team_classifier(
    video_path: str,
    detector: Any,
    team_classifier: Any,
    *,
    stride: int,
    max_crops: int,
) -> None:
    """Fit the SigLIP team classifier once on stride-sampled player crops."""
    import supervision as sv

    crops: list[np.ndarray] = []
    for frame in sv.get_video_frames_generator(source_path=video_path, stride=stride):
        detections = _detect_players(detector, frame)
        crops.extend(_central_crops(frame, detections))
        if len(crops) >= max_crops:
            break

    if not crops:
        raise RuntimeError("No players detected; cannot fit the team classifier")

    team_classifier.fit(crops)


def process_video(
    video_path: str,
    *,
    detector: Any,
    ocr: Any,
    predictor: Any,
    team_classifier: Any,
    batch_size: int = 30,
    ocr_interval: int = 5,
    team_fit_stride: int = 30,
    team_fit_max_crops: int = 200,
    max_frames: int | None = None,
    source: str = "modal",
    batch_id: str | None = None,
) -> Iterator[ColabDetectionBatch]:
    """Run the full pipeline over a video, yielding ``ColabDetectionBatch``.

    Yields one batch every ``batch_size`` processed frames, plus a final batch
    flagged ``final_batch=True``. Team IDs are assigned once on the first frame
    and reused per ``tracker_id``; jersey numbers are validated across time and
    OCR is only run every ``ocr_interval`` frames to save GPU. ``max_frames``
    caps how many frames are processed (used to keep smoke tests fast).
    """
    import supervision as sv
    from sports import ConsecutiveValueTracker

    video_info = sv.VideoInfo.from_video_path(video_path)
    fps = float(video_info.fps) if video_info.fps else 30.0

    # Stage 0: fit the team classifier once on representative crops.
    _fit_team_classifier(
        video_path,
        detector,
        team_classifier,
        stride=team_fit_stride,
        max_crops=team_fit_max_crops,
    )

    tracker = SAM2Tracker(predictor)
    number_validator = ConsecutiveValueTracker(n_consecutive=3)

    # tracker_id -> team_id (assigned once on the first frame).
    track_team: dict[int, int] = {}
    # tracker_id -> (class_id, class_name, confidence) from the latest detection.
    track_class: dict[int, tuple[int, str, float]] = {}

    frames: list[ColabFramePayload] = []
    processed = 0
    seeded = False

    for index, frame in enumerate(sv.get_video_frames_generator(source_path=video_path)):
        frame_h, frame_w = frame.shape[:2]

        if not seeded:
            # Seed SAM-2 + assign teams on the FIRST frame that has players. Some
            # clips open on a logo/empty frame, so we cannot assume frame 0 works.
            seed = _detect_players(detector, frame)
            if len(seed) == 0:
                # Nothing to track yet: emit an empty frame and keep scanning.
                frames.append(
                    ColabFramePayload(
                        frame_number=index,
                        timestamp_sec=index / fps,
                        detections=[],
                    )
                )
                processed += 1
                if len(frames) >= batch_size:
                    yield ColabDetectionBatch(
                        batch_id=batch_id,
                        source=source,
                        final_batch=False,
                        frames=frames,
                    )
                    frames = []
                continue
            seed.tracker_id = np.arange(1, len(seed.class_id) + 1)
            crops = _central_crops(frame, seed)
            teams = np.array(team_classifier.predict(crops))
            for tid, team_id in zip(seed.tracker_id, teams):
                track_team[int(tid)] = int(team_id)
            for tid, cid, conf in zip(seed.tracker_id, seed.class_id, seed.confidence):
                track_class[int(tid)] = (
                    int(cid),
                    CLASS_ID_TO_NAME.get(int(cid), "player"),
                    float(conf),
                )
            tracker.prompt_first_frame(frame, seed)
            seeded = True

        player_detections = tracker.propagate(frame)

        # Periodically run RF-DETR for jersey numbers + fresh action classes.
        if index % ocr_interval == 0:
            result = detector.infer(
                frame,
                confidence=PLAYER_DETECTION_MODEL_CONFIDENCE,
                iou_threshold=PLAYER_DETECTION_MODEL_IOU_THRESHOLD,
            )[0]
            all_detections = sv.Detections.from_inference(result)

            # Refresh per-track action class by matching RF-DETR player boxes.
            action_det = all_detections[np.isin(all_detections.class_id, PLAYER_CLASS_IDS)]
            if len(action_det) and player_detections.mask is not None:
                action_masks = sv.xyxy_to_mask(
                    boxes=action_det.xyxy, resolution_wh=(frame_w, frame_h)
                )
                ios = sv.mask_iou_batch(
                    masks_true=player_detections.mask,
                    masks_detection=action_masks,
                    overlap_metric=sv.OverlapMetric.IOS,
                )
                assigned: set[int] = set()
                for p_idx, a_idx in _coords_above_threshold(ios, 0.5):
                    if p_idx in assigned:
                        continue
                    assigned.add(p_idx)
                    tid = int(player_detections.tracker_id[p_idx])
                    cid = int(action_det.class_id[a_idx])
                    conf = float(action_det.confidence[a_idx])
                    track_class[tid] = (cid, CLASS_ID_TO_NAME.get(cid, "player"), conf)

            # Jersey number detection + OCR, matched to tracks via mask IoS.
            number_det = all_detections[all_detections.class_id == NUMBER_CLASS_ID]
            if len(number_det) and player_detections.mask is not None:
                number_det.mask = sv.xyxy_to_mask(
                    boxes=number_det.xyxy, resolution_wh=(frame_w, frame_h)
                )
                number_crops = [
                    sv.crop_image(frame, xyxy)
                    for xyxy in sv.clip_boxes(
                        sv.pad_boxes(xyxy=number_det.xyxy, px=10, py=10),
                        (frame_w, frame_h),
                    )
                ]
                numbers = recognize_jersey_numbers(
                    ocr,
                    number_crops,
                    NUMBER_RECOGNITION_MODEL_PROMPT,
                )
                ios = sv.mask_iou_batch(
                    masks_true=player_detections.mask,
                    masks_detection=number_det.mask,
                    overlap_metric=sv.OverlapMetric.IOS,
                )
                pairs = _coords_above_threshold(ios, 0.9)
                if pairs:
                    player_idx, number_idx = zip(*pairs)
                    matched_tids = [
                        int(player_detections.tracker_id[i]) for i in player_idx
                    ]
                    matched_numbers = [numbers[int(i)] for i in number_idx]
                    number_validator.update(
                        tracker_ids=matched_tids, values=matched_numbers
                    )

        validated = number_validator.get_validated(
            tracker_ids=player_detections.tracker_id
        )

        detections_out: list[ColabDetection] = []
        for i, tid in enumerate(player_detections.tracker_id):
            tid = int(tid)
            x1, y1, x2, y2 = (float(v) for v in player_detections.xyxy[i])

            class_id, class_name, confidence = track_class.get(
                tid, (3, "player", None)
            )
            team_id = track_team.get(tid)
            team_name = TEAM_NAMES.get(team_id) if team_id is not None else None

            raw_number = validated[i] if i < len(validated) else None
            jersey_number: int | None = None
            if raw_number not in (None, ""):
                number_str = str(raw_number).strip()
                if number_str.isdigit():
                    jersey_number = int(number_str)

            player_name = roster_name(team_name, jersey_number)

            detections_out.append(
                ColabDetection(
                    track_id=tid,
                    bbox=ColabBoundingBox(x1=x1, y1=y1, x2=x2, y2=y2),
                    class_id=class_id,
                    class_name=class_name,
                    confidence=confidence,
                    team_id=team_id,
                    team_name=team_name,
                    jersey_number=jersey_number,
                    player_name=player_name,
                )
            )

        frames.append(
            ColabFramePayload(
                frame_number=index,
                timestamp_sec=index / fps,
                detections=detections_out,
            )
        )
        processed += 1

        if len(frames) >= batch_size:
            yield ColabDetectionBatch(
                batch_id=batch_id,
                source=source,
                final_batch=False,
                frames=frames,
            )
            frames = []

        if max_frames is not None and processed >= max_frames:
            break

    # Always emit a final batch (even if empty) to signal completion.
    yield ColabDetectionBatch(
        batch_id=batch_id,
        source=source,
        final_batch=True,
        frames=frames,
    )

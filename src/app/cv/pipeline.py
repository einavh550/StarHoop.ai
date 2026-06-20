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

import logging
from collections import Counter, deque
from typing import Any, Iterator

import numpy as np

from app.core.config import settings
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

logger = logging.getLogger(__name__)


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

    def add_tracks(self, frame: np.ndarray, boxes: np.ndarray, obj_ids: list[int]) -> None:
        """Re-prompt SAM-2 mid-stream with new boxes (Fix 5 reconciliation).

        Used by periodic re-detection to start tracking players that entered
        late, were lost to occlusion, or were missed at seed time. Each box is
        added as a new object so subsequent ``propagate`` calls carry it.
        """
        import torch

        if not self._prompted:
            raise RuntimeError("Call prompt_first_frame before add_tracks")

        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
            for xyxy, obj_id in zip(boxes, obj_ids):
                bbox = np.asarray([xyxy], dtype=np.float32)
                self.predictor.add_new_prompt(frame_idx=0, obj_id=int(obj_id), bbox=bbox)

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


def _assign_actions(
    ios_matrix: np.ndarray,
    threshold: float,
    *,
    exclusive_detections: bool,
) -> list[tuple[int, int]]:
    """Greedily assign RF-DETR detections (cols) to SAM-2 tracks (rows) by IoS.

    Pairs are consumed best-first. Each track (``p_idx``) is always assigned at
    most once. When ``exclusive_detections`` is set (Fix 2), each detection
    (``a_idx``) is also consumed at most once, so a single blocker box can no
    longer be attributed to two players (the shot-labeled-as-block root cause).
    """
    pairs: list[tuple[int, int]] = []
    assigned_tracks: set[int] = set()
    assigned_dets: set[int] = set()
    for p_idx, a_idx in _coords_above_threshold(ios_matrix, threshold):
        if p_idx in assigned_tracks:
            continue
        if exclusive_detections and a_idx in assigned_dets:
            continue
        assigned_tracks.add(p_idx)
        assigned_dets.add(a_idx)
        pairs.append((p_idx, a_idx))
    return pairs


def _box_iou(box_a: np.ndarray, box_b: np.ndarray) -> float:
    """IoU of two ``[x1, y1, x2, y2]`` boxes (0.0 when they do not intersect)."""
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter = inter_w * inter_h
    if inter <= 0.0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return float(inter / union) if union > 0 else 0.0


def _resolve_overlapping_tracks(
    xyxy: np.ndarray,
    teams: list[int | None],
    *,
    iou_threshold: float,
) -> list[int]:
    """Return the indices to KEEP after collapsing heavily-overlapping boxes.

    Fix 4 — in crowds, SAM-2 sometimes carries two tracks on one physical player
    (or a lost track lingers on top of the live one). When two SAME-TEAM boxes
    overlap above ``iou_threshold`` the smaller-area box is suppressed, leaving a
    single box on the blob. Boxes of different (or unknown) teams are never
    merged, so a legitimate offense/defense contest is preserved.
    """
    count = len(xyxy)
    areas = [
        max(0.0, float(box[2] - box[0])) * max(0.0, float(box[3] - box[1]))
        for box in xyxy
    ]
    suppressed: set[int] = set()
    for i in range(count):
        if i in suppressed:
            continue
        for j in range(i + 1, count):
            if j in suppressed:
                continue
            if teams[i] is None or teams[j] is None or teams[i] != teams[j]:
                continue
            if _box_iou(xyxy[i], xyxy[j]) <= iou_threshold:
                continue
            # Drop the smaller box; keep the larger, more complete detection.
            loser = j if areas[j] <= areas[i] else i
            suppressed.add(loser)
            if loser == i:
                break
    return [i for i in range(count) if i not in suppressed]


def _find_unmatched_detections(
    detection_xyxy: np.ndarray,
    track_xyxy: np.ndarray,
    *,
    match_iou: float,
) -> list[int]:
    """Indices of fresh detections not covered by any active SAM-2 track.

    A detection is "unmatched" when its best IoU against every current track box
    is at or below ``match_iou`` — i.e. it is a player nobody is tracking yet
    (late entrant / recovered after occlusion / missed at seed). These are the
    boxes Fix 5 re-prompts SAM-2 with.
    """
    unmatched: list[int] = []
    for d_idx in range(len(detection_xyxy)):
        dbox = detection_xyxy[d_idx]
        best = 0.0
        for t_idx in range(len(track_xyxy)):
            best = max(best, _box_iou(dbox, track_xyxy[t_idx]))
            if best > match_iou:
                break
        if best <= match_iou:
            unmatched.append(d_idx)
    return unmatched


def _majority_action(
    history: list[tuple[int, str, float]],
) -> tuple[int, str, float]:
    """Return the dominant ``(class_id, class_name, confidence)`` in ``history``.

    Picks the ``class_id`` observed most often over the recent window (instead of
    last-write-wins), breaking ties by the highest summed confidence. The
    returned confidence is the best confidence seen for the winning class. This
    smooths single-frame misclassifications (e.g. one frame of ``shot-block``
    inside a run of ``jump-shot``).
    """
    if not history:
        raise ValueError("history must contain at least one observation")

    votes: Counter[int] = Counter()
    summed_conf: dict[int, float] = {}
    best: dict[int, tuple[str, float]] = {}
    for class_id, class_name, conf in history:
        votes[class_id] += 1
        summed_conf[class_id] = summed_conf.get(class_id, 0.0) + conf
        prev = best.get(class_id)
        if prev is None or conf > prev[1]:
            best[class_id] = (class_name, conf)

    winner = max(votes, key=lambda cid: (votes[cid], summed_conf[cid]))
    name, conf = best[winner]
    return (winner, name, conf)


def _fit_team_classifier(
    video_path: str,
    detector: Any,
    team_classifier: Any,
    *,
    stride: int,
    max_crops: int,
    start_frame: int = 0,
    end_frame: int | None = None,
) -> None:
    """Fit the SigLIP team classifier once on stride-sampled player crops."""
    import supervision as sv

    crops: list[np.ndarray] = []
    for frame in sv.get_video_frames_generator(
        source_path=video_path, stride=stride, start=start_frame, end=end_frame
    ):
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
    frame_stride: int = 1,
    start_frame: int = 0,
    end_frame: int | None = None,
    track_id_offset: int = 0,
    team_fit_stride: int = 30,
    team_fit_max_crops: int = 200,
    max_frames: int | None = None,
    source: str = "modal",
    batch_id: str | None = None,
    action_temporal_voting: bool | None = None,
    action_vote_window: int | None = None,
    overlap_resolution: bool | None = None,
    overlap_resolution_iou: float | None = None,
    periodic_redetect_interval: int | None = None,
    periodic_redetect_match_iou: float | None = None,
) -> Iterator[ColabDetectionBatch]:
    """Run the full pipeline over a video, yielding ``ColabDetectionBatch``.

    Yields one batch every ``batch_size`` processed frames, plus a final batch
    flagged ``final_batch=True``. Team IDs are assigned once on the first frame
    and reused per ``tracker_id``; jersey numbers are validated across time and
    OCR is only run every ``ocr_interval`` *processed* frames to save GPU.

    ``frame_stride`` is the temporal subsampling factor: only every Nth source
    frame is processed (stride 3 over a 30fps clip ≈ 10 effective fps). This is
    the single biggest throughput lever — detection density for highlights does
    not need every frame. ``frame_number``/``timestamp_sec`` are always reported
    against the REAL source frame index, so downstream timing stays correct
    regardless of stride.

    ``start_frame``/``end_frame`` bound the time-segment this worker owns —
    used for chunked parallel processing. ``track_id_offset`` shifts all SAM-2
    tracker IDs by a fixed amount so chunks never collide in the DB.
    ``max_frames`` caps how many processed frames are emitted (smoke tests).
    """
    frame_stride = max(1, int(frame_stride))
    track_id_offset = max(0, int(track_id_offset))
    # Resolve remediation flags: explicit args win, else fall back to settings so
    # Modal can toggle them via env without changing call sites. Defaults are the
    # original last-write-wins behavior.
    if action_temporal_voting is None:
        action_temporal_voting = settings.action_temporal_voting
    if action_vote_window is None:
        action_vote_window = settings.action_vote_window
    action_vote_window = max(1, int(action_vote_window))
    if overlap_resolution is None:
        overlap_resolution = settings.overlap_resolution
    if overlap_resolution_iou is None:
        overlap_resolution_iou = settings.overlap_resolution_iou
    if periodic_redetect_interval is None:
        periodic_redetect_interval = settings.periodic_redetect_interval
    periodic_redetect_interval = max(0, int(periodic_redetect_interval))
    if periodic_redetect_match_iou is None:
        periodic_redetect_match_iou = settings.periodic_redetect_match_iou
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
        start_frame=start_frame,
        end_frame=end_frame,
    )

    tracker = SAM2Tracker(predictor)
    number_validator = ConsecutiveValueTracker(n_consecutive=3)

    # tracker_id -> team_id (assigned once on the first frame).
    track_team: dict[int, int] = {}
    # tracker_id -> (class_id, class_name, confidence) from the latest detection.
    track_class: dict[int, tuple[int, str, float]] = {}
    # tracker_id -> recent (class_id, class_name, confidence) observations, used
    # for temporal majority voting on the action label when enabled.
    track_class_history: dict[int, deque[tuple[int, str, float]]] = {}

    frames: list[ColabFramePayload] = []
    processed = 0
    seeded = False
    # Fix 5 reconciliation state. New tracks get ids inside this chunk's block
    # (offset .. offset+10000) so they never collide with other chunks or the
    # seed ids. Disabled at runtime if the predictor rejects mid-stream prompts.
    redetect_disabled = False
    next_redetect_id = track_id_offset + 5000

    for strided_index, frame in enumerate(
        sv.get_video_frames_generator(
            source_path=video_path, stride=frame_stride, start=start_frame, end=end_frame
        )
    ):
        # Report against the REAL source frame index so timestamps/frame numbers
        # are independent of the subsampling stride.
        index = start_frame + strided_index * frame_stride
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
            seed.tracker_id = np.arange(1, len(seed.class_id) + 1) + track_id_offset
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

        # Fix 4: collapse heavily-overlapping same-team boxes so a crowded blob
        # is not double-counted as two tracks on one player.
        if overlap_resolution and len(player_detections):
            teams = [track_team.get(int(tid)) for tid in player_detections.tracker_id]
            keep = _resolve_overlapping_tracks(
                player_detections.xyxy, teams, iou_threshold=overlap_resolution_iou
            )
            if len(keep) < len(player_detections):
                player_detections = player_detections[keep]

        # Fix 5: periodic re-detection & track reconciliation. Every N processed
        # frames, re-run RF-DETR and re-prompt SAM-2 with any player it is not
        # already tracking, recovering late entrants / occluded / missed players.
        if (
            periodic_redetect_interval > 0
            and not redetect_disabled
            and strided_index > 0
            and strided_index % periodic_redetect_interval == 0
        ):
            fresh = _detect_players(detector, frame)
            track_xyxy = (
                player_detections.xyxy
                if len(player_detections)
                else np.empty((0, 4), dtype=np.float32)
            )
            unmatched = (
                _find_unmatched_detections(
                    fresh.xyxy, track_xyxy, match_iou=periodic_redetect_match_iou
                )
                if len(fresh)
                else []
            )
            if unmatched:
                new_dets = fresh[unmatched]
                new_ids = [next_redetect_id + k for k in range(len(unmatched))]
                try:
                    tracker.add_tracks(frame, new_dets.xyxy, new_ids)
                except Exception as exc:  # noqa: BLE001 - never crash the pipeline
                    logger.warning(
                        "periodic re-detect disabled: predictor rejected mid-stream prompt (%s)",
                        exc,
                    )
                    redetect_disabled = True
                else:
                    crops = _central_crops(frame, new_dets)
                    teams = np.array(team_classifier.predict(crops)) if crops else []
                    for k, obj_id in enumerate(new_ids):
                        if k < len(teams):
                            track_team[obj_id] = int(teams[k])
                        cid = int(new_dets.class_id[k])
                        conf = float(new_dets.confidence[k])
                        track_class[obj_id] = (cid, CLASS_ID_TO_NAME.get(cid, "player"), conf)
                    next_redetect_id += len(unmatched)
                    logger.info(
                        "periodic re-detect: added %d new track(s) at frame %d",
                        len(unmatched),
                        index,
                    )

        # Periodically run RF-DETR for jersey numbers + fresh action classes.
        # Cadence is measured in PROCESSED frames so it is stride-independent.
        if strided_index % ocr_interval == 0:
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
                for p_idx, a_idx in _assign_actions(
                    ios, 0.5, exclusive_detections=action_temporal_voting
                ):
                    tid = int(player_detections.tracker_id[p_idx])
                    cid = int(action_det.class_id[a_idx])
                    conf = float(action_det.confidence[a_idx])
                    name = CLASS_ID_TO_NAME.get(cid, "player")
                    if action_temporal_voting:
                        history = track_class_history.setdefault(
                            tid, deque(maxlen=action_vote_window)
                        )
                        history.append((cid, name, conf))
                        track_class[tid] = _majority_action(list(history))
                    else:
                        track_class[tid] = (cid, name, conf)

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

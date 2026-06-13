"""Heuristic basketball action recognition service."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from statistics import mean

from sqlalchemy.orm import Session

from app.db.models import ActionDetection, DetectionFrame, JerseyDetection, VideoJob


@dataclass
class TrackObservation:
    frame_number: int
    timestamp_sec: float
    center_y: float
    detection_confidence: float


@dataclass
class ActionCandidate:
    track_id: int
    action_type: str
    action_confidence: float
    start_frame: int
    end_frame: int
    start_timestamp_sec: float
    end_timestamp_sec: float
    mapped_player_id: int | None


class ActionRecognizer:
    """Recognize simple basketball actions from tracked detections."""

    @staticmethod
    def detect_actions_from_video(db: Session, video_job_id: int) -> list[ActionCandidate]:
        job = db.query(VideoJob).filter(VideoJob.id == video_job_id).first()
        if not job:
            raise ValueError(f"VideoJob {video_job_id} not found")

        if job.status != "completed":
            raise ValueError(f"VideoJob {video_job_id} must be completed before action recognition")

        frames = (
            db.query(DetectionFrame)
            .filter(DetectionFrame.video_job_id == video_job_id)
            .order_by(DetectionFrame.frame_number.asc())
            .all()
        )

        if not frames:
            return []

        player_mapping_by_track = {
            det.track_id: det.mapped_player_id
            for det in db.query(JerseyDetection)
            .filter(JerseyDetection.video_job_id == video_job_id)
            .all()
        }

        observations_by_track: dict[int, list[TrackObservation]] = defaultdict(list)
        for frame in frames:
            for det in frame.detections_json:
                track_id = det.get("track_id")
                bbox = det.get("bbox") or {}
                class_name = (det.get("class_name") or "").lower()

                if class_name not in {"person", "player"} or track_id is None:
                    continue

                y1 = bbox.get("y1")
                y2 = bbox.get("y2")
                if y1 is None or y2 is None:
                    continue

                center_y = float(y1 + y2) / 2.0
                observations_by_track[int(track_id)].append(
                    TrackObservation(
                        frame_number=int(frame.frame_number),
                        timestamp_sec=float(frame.timestamp_sec),
                        center_y=center_y,
                        detection_confidence=float(det.get("confidence", 0.0)),
                    )
                )

        action_candidates: list[ActionCandidate] = []
        for track_id, observations in observations_by_track.items():
            segments = ActionRecognizer._split_contiguous_segments(observations)
            for segment in segments:
                shot = ActionRecognizer._detect_shot_attempt_for_segment(
                    track_id=track_id,
                    observations=segment,
                    mapped_player_id=player_mapping_by_track.get(track_id),
                )
                if shot is not None:
                    action_candidates.append(shot)

        action_candidates = ActionRecognizer._filter_track_candidates(action_candidates)
        action_candidates.sort(key=lambda a: a.action_confidence, reverse=True)
        return action_candidates

    @staticmethod
    def _filter_track_candidates(
        action_candidates: list[ActionCandidate],
        min_separation_frames: int = 24,
        overlap_threshold: float = 0.65,
    ) -> list[ActionCandidate]:
        """Reduce duplicate detections on the same track for nearby/overlapping windows."""
        grouped: dict[int, list[ActionCandidate]] = defaultdict(list)
        for candidate in action_candidates:
            grouped[candidate.track_id].append(candidate)

        filtered: list[ActionCandidate] = []
        for track_candidates in grouped.values():
            # Keep the strongest candidates first; suppress near-duplicates.
            sorted_candidates = sorted(track_candidates, key=lambda c: c.action_confidence, reverse=True)
            accepted: list[ActionCandidate] = []

            for candidate in sorted_candidates:
                keep = True
                for prev in accepted:
                    overlap = ActionRecognizer._frame_window_overlap_ratio(candidate, prev)
                    center_gap = abs(
                        ((candidate.start_frame + candidate.end_frame) // 2)
                        - ((prev.start_frame + prev.end_frame) // 2)
                    )
                    if overlap >= overlap_threshold or center_gap < min_separation_frames:
                        keep = False
                        break

                if keep:
                    accepted.append(candidate)

            filtered.extend(accepted)

        return filtered

    @staticmethod
    def _frame_window_overlap_ratio(a: ActionCandidate, b: ActionCandidate) -> float:
        left = max(a.start_frame, b.start_frame)
        right = min(a.end_frame, b.end_frame)
        if right < left:
            return 0.0

        overlap = right - left + 1
        a_len = (a.end_frame - a.start_frame) + 1
        b_len = (b.end_frame - b.start_frame) + 1
        return overlap / float(min(a_len, b_len))

    @staticmethod
    def persist_action_detections(
        db: Session,
        video_job_id: int,
        action_candidates: list[ActionCandidate],
    ) -> list[ActionDetection]:
        # Replace previous MVP detections for idempotent endpoint behavior.
        db.query(ActionDetection).filter(ActionDetection.video_job_id == video_job_id).delete()

        created: list[ActionDetection] = []
        for candidate in action_candidates:
            record = ActionDetection(
                video_job_id=video_job_id,
                track_id=candidate.track_id,
                action_type=candidate.action_type,
                action_confidence=candidate.action_confidence,
                start_frame=candidate.start_frame,
                end_frame=candidate.end_frame,
                start_timestamp_sec=Decimal(f"{candidate.start_timestamp_sec:.3f}"),
                end_timestamp_sec=Decimal(f"{candidate.end_timestamp_sec:.3f}"),
                mapped_player_id=candidate.mapped_player_id,
            )
            db.add(record)
            created.append(record)

        db.commit()
        return created

    @staticmethod
    def _split_contiguous_segments(
        observations: list[TrackObservation],
        max_frame_gap: int = 5,
    ) -> list[list[TrackObservation]]:
        if not observations:
            return []

        sorted_obs = sorted(observations, key=lambda o: o.frame_number)
        segments: list[list[TrackObservation]] = [[sorted_obs[0]]]

        for obs in sorted_obs[1:]:
            prev = segments[-1][-1]
            if obs.frame_number - prev.frame_number <= max_frame_gap:
                segments[-1].append(obs)
            else:
                segments.append([obs])

        return segments

    @staticmethod
    def _detect_shot_attempt_for_segment(
        track_id: int,
        observations: list[TrackObservation],
        mapped_player_id: int | None,
    ) -> ActionCandidate | None:
        # Need enough temporal context to infer up/down shooting arc from player center.
        if len(observations) < 7:
            return None

        center_ys = [o.center_y for o in observations]
        min_center_y = min(center_ys)
        apex_idx = center_ys.index(min_center_y)

        # Apex should be in the interior, not at the very edges.
        if apex_idx < 2 or apex_idx > len(observations) - 3:
            return None

        start_obs = observations[0]
        apex_obs = observations[apex_idx]
        end_obs = observations[-1]

        upward_motion_px = start_obs.center_y - apex_obs.center_y
        downward_motion_px = end_obs.center_y - apex_obs.center_y
        duration_frames = end_obs.frame_number - start_obs.frame_number
        mean_det_conf = mean(o.detection_confidence for o in observations)

        # Stricter heuristic thresholds to reduce false positives in crowded scenes.
        if upward_motion_px < 26.0 or downward_motion_px < 14.0:
            return None

        if duration_frames < 6 or duration_frames > 40:
            return None

        if mean_det_conf < 0.60:
            return None

        rebound_ratio = downward_motion_px / max(upward_motion_px, 1e-6)
        if rebound_ratio < 0.45 or rebound_ratio > 1.80:
            return None

        motion_score = min((upward_motion_px + downward_motion_px) / 70.0, 1.0)
        duration_score = min(duration_frames / 20.0, 1.0)

        confidence = min(0.99, 0.20 + (0.45 * motion_score) + (0.20 * duration_score) + (0.15 * mean_det_conf))

        return ActionCandidate(
            track_id=track_id,
            action_type="shot_attempt",
            action_confidence=round(confidence, 3),
            start_frame=start_obs.frame_number,
            end_frame=end_obs.frame_number,
            start_timestamp_sec=start_obs.timestamp_sec,
            end_timestamp_sec=end_obs.timestamp_sec,
            mapped_player_id=mapped_player_id,
        )

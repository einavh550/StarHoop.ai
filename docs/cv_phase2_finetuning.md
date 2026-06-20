# CV Pipeline — Phase 2: Data Curation & Model Fine-Tuning (Deferred)

This document is the **deferred** Phase 2 track of the CV Pipeline Remediation.
Phase 1 (shipped) treats the Roboflow models as fixed and fixes the five QA bugs
with deterministic, feature-flagged post-processing. Phase 2 closes the gap that
**only** retraining can close: detector/OCR errors at their source.

> Status: planned, not scheduled. Do **not** start Phase 2 until the Phase 1
> flags are enabled in production and the golden-job regression harness
> (`tests/regression/`, `app.cv.qa_metrics`) shows the residual error is
> dominated by model mistakes rather than pipeline logic.

## Fixed models today

| Role | Model ID | Phase 1 treatment |
| --- | --- | --- |
| Player / action detection | `basketball-player-detection-3-ycjdo/4` | fixed; exclusive IoS + temporal voting + gating downstream |
| Jersey OCR | `basketball-jersey-numbers-ocr/3` | fixed; consensus voting + confidence thresholds downstream |
| Team color | SigLIP `TeamClassifier` (fit per video) | fixed; used as opponent gate only |
| Tracking | SAM-2 (realtime) | fixed; consolidation, overlap resolution, periodic re-detect downstream |

## Why Phase 2 is needed (residual errors Phase 1 cannot remove)

Phase 1 suppresses *symptoms* (duplicate clips, phantom blocks, double boxes).
It cannot recover information the models never produced:

- **Shot-vs-block confusion** that is wrong on the *majority* of frames (temporal
  voting only helps when the correct label is the plurality).
- **Seed-frame and crowd misses** where RF-DETR never emits a box, so there is
  nothing for SAM-2 to track even with periodic re-detection.
- **Low-recall / low-confidence OCR** on motion-blurred or angled jerseys, which
  caps how often a track can be mapped at all.

## Data-curation plan (mine the failures we already have)

Every fix in Phase 1 also defines a *hard-negative miner*. Use the regression
metrics to surface candidate frames from real jobs (e.g. job 18), then label:

1. **Shot/block hard negatives** — frames where `event_type_precision`
   (`app.cv.qa_metrics.event_type_precision`) flags a predicted `shot_block` or
   `jump_shot` with no matching ground truth. Crop the player + ball region and
   relabel shot vs. block vs. neither. Target a class-balanced set.
2. **Crowd / occlusion frames** — frames where `duplicate_identity_frame_count`
   or the overlap resolver fired. Label every distinct player box so the
   detector learns to separate contesting bodies.
3. **Missed-detection frames** — frames where periodic re-detection added a late
   track. The pre-detection frames are exactly the misses; label the missed
   players as positives.
4. **OCR confidence propagation** — keep `jersey_confidence` per detection
   (already persisted) and curate a calibration set of crops with verified
   numbers, including hard cases (blur, partial, rotated).

A small labeling spec (COCO-style boxes + action class + jersey string) keeps
this compatible with Roboflow re-training.

## Model work (scheduled later)

- **Detector recall tuning**: class-balanced fine-tune on the curated set;
  re-evaluate the seed-frame miss rate and crowd separation against the harness.
- **Shot/block head**: targeted fine-tune (or a small dedicated classifier on
  the action crop) using the hard negatives; gate by the same
  `event_type_precision` metric before flipping any flag.
- **OCR confidence calibration**: temperature-scale or recalibrate the OCR
  confidence so `ocr_confidence_strict` / `ocr_confidence_threshold` cut points
  in `config.py` map to true precision.
- **Optional appearance ReID head**: an embedding to re-link SAM-2 fragments by
  appearance, complementing the jersey-based `consolidate_tracks_by_player`
  heuristic for players whose number is never read.

## Acceptance gates (reuse Phase 0 harness)

Before any retrained model replaces a fixed one:

1. Run the golden-job harness; require **non-regression** on every metric
   (`duplicate_clip_rate`, `tracks_per_player`, `duplicate_identity_frame_count`,
   `event_type_precision`).
2. Require a measurable **improvement** on the targeted metric for that model
   (e.g. shot/block precision for the action head).
3. Ship behind the existing per-fix feature flags so rollback is a config flip,
   never a redeploy.

## Out of scope / explicitly preserved

- Single-team assumption stays: we map to one coached `VideoJob.team_id`; the
  opponent gate (`opponent_team_gate`) only prevents mis-mapping, it does not
  add multi-team support.
- M5/M6 highlight + compose response schemas are untouched, so the Android
  integration is unaffected by any Phase 2 work.

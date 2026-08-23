# Labeled Dataset Validation - 2026-06-23

## 1. Scope

This validation is a reproducible offline / quasi-realtime experiment on labeled local datasets. It is not a live RTSP field demonstration.

Boundaries:

- Production code was not modified.
- `.env` was not modified by this stage.
- No model training was performed.
- Temporal was forced disabled in the evaluation process.
- 0-5 VisualRiskMarker was not enabled as realtime main functionality.
- `MAIN_SYSTEM_REPORT_DRY_RUN=true` was forced in the evaluation process.
- No real POST was sent.
- No git add / commit was performed.

## 2. Dataset

- labels.csv: `D:\Program\vision_service\artifacts\labeled_dataset_validation_20260623\labels.csv`
- evaluated videos: `12`
- Label granularity: video-level fall / non_fall labels. `fall_start_sec` / `fall_end_sec` are supported by the CSV schema but blank in the generated default labels.

## 3. Models And Runtime Chain

- YOLO person: `yolov8n.pt`
- YOLO fall detector: `models/yolo_fall_detector_phase9_selected.pt`
- Pose provider: `yolo11_legacy`
- YOLO11 pose path: `yolo11n-pose.pt`
- YOLO pose fallback path: `yolov8n-pose.pt`
- ByteTrack: `ultralytics.trackers.byte_tracker.BYTETracker`
- Temporal enabled: `False`
- Reporter dry-run: `True`

## 4. Metrics

| Metric | Value |
| --- | ---: |
| TP | 5 |
| FP | 5 |
| FN | 0 |
| TN | 2 |
| Precision | 0.5 |
| Recall | 1.0 |
| F1-score | 0.6667 |
| False Positive Rate | 0.7143 |
| Avg offline processing FPS | 1.9562 |
| Avg total model latency ms | 496.1482 |
| Avg pose attached rate | 0.828 |
| Avg keypoint count | 17.0 |
| Avg keypoint_count=17 rate | 0.828 |
| Avg skeleton confidence | 0.8829 |
| Dry-run all videos | True |
| No real POST all videos | True |

Scene false positives: `{"walk": 1, "no_person": 1, "sit": 2, "squat": 1}`

## 5. Per-video Results

| Label | Scene | Outcome | Predicted | Peak State | Peak Risk | Fall Frames | Pose Attach Rate | Reporter | Video |
| --- | --- | --- | --- | --- | --- | ---: | ---: | --- | --- |
| fall | unknown | TP | True | fallen_candidate | medium | 7 | 1.0 | no_real_post | video.mp4 |
| non_fall | walk | FP | True | fallen_candidate | high | 7 | 1.0 | no_real_post | video.mp4 |
| fall | unknown | TP | True | fallen_candidate | high | 10 | 0.8889 | no_real_post | video.mp4 |
| fall | unknown | TP | True | fallen_candidate | high | 5 | 0.7143 | no_real_post | video.mp4 |
| non_fall | no_person | FP | True | fallen_candidate | high | 1 | 1.0 | no_real_post | video.mp4 |
| non_fall | sit | FP | True | fallen_candidate | high | 2 | 1.0 | no_real_post | video.mp4 |
| non_fall | sit | FP | True | fallen_candidate | high | 3 | 0.6667 | no_real_post | video.mp4 |
| non_fall | squat | FP | True | fallen_candidate | high | 5 | 1.0 | no_real_post | video.mp4 |
| fall | fall | TP | True | fallen_candidate | high | 6 | 0.1667 | no_real_post | 01.mp4 |
| fall | fall | TP | True | fallen_candidate | medium | 10 | 0.5 | no_real_post | 02.mp4 |
| non_fall | walk | TN | False |  |  | 27 | 1.0 | no_real_post | 01.mp4 |
| non_fall | walk | TN | False |  |  | 0 | 1.0 | no_real_post | 02.mp4 |

## 6. Artifacts

- `D:\Program\vision_service\artifacts\labeled_dataset_validation_20260623\metrics_summary.csv`
- `D:\Program\vision_service\artifacts\labeled_dataset_validation_20260623\per_video_results.csv`
- `D:\Program\vision_service\artifacts\labeled_dataset_validation_20260623\metrics_summary.json`
- `D:\Program\vision_service\artifacts\labeled_dataset_validation_20260623\confusion_matrix.png`
- `D:\Program\vision_service\artifacts\labeled_dataset_validation_20260623\sample_frames`
- `D:\Program\vision_service\artifacts\labeled_dataset_validation_20260623\frame_results.jsonl`

## 7. Acceptance Interpretation

- Fall videos are counted positive only when current runtime output fields reach `fallen_candidate` / `fallen_confirmed` or `high` / `critical`.
- Non-fall videos are counted false positive when those same runtime fields reach a positive state.
- Pose is evaluated without keypoint labels by pose_attached rate, average keypoint count, keypoint_count=17 rate, skeleton confidence, rejected_reason distribution, and pose latency.
- Reporter safety passes only if dry-run remains true and no real POST is observed.

## 8. Demo Positioning

The fall recognition claim should be grounded in labeled dataset metrics and the existing local replay end-to-end evidence. RTSP camera remains an optional online-ingest demonstration only, not the main proof of fall recognition stability.

# Pose Model To Main-System Alert Qualification Plan - 2026-06-22

## Stage 0 Baseline Freeze

This document starts the isolated qualification branch for future pose-model work. It intentionally freezes the current stable demo baseline before any dataset inventory, annotation, pose integration, training, or main-system alert promotion work.

Current branch:

```text
feature/pose-model-qualification
```

Stable rollback tag:

```text
stable-demo-20260622-no-pose-dryrun
```

Stable checkpoint commit:

```text
fdc4b19 Checkpoint stable no-pose dry-run demo handoff
```

Baseline commits included in the stable node:

```text
7af5736 Add bridge reporter dry-run guard
d9818f8 Add throttled local replay for fall demo validation
540e4f4 Stabilize frontend runtime status and overlay guards
52ad211 Enhance selected target overlay with rainbow frame
fdc4b19 Checkpoint stable no-pose dry-run demo handoff
```

Baseline runtime:

```text
MAIN_SYSTEM_REPORT_DRY_RUN=true
bridge_target=http://192.168.8.254:8000/api/v1/video-bridge/fall-events
MAIN_SYSTEM_ALERT_TOKEN_HEADER=X-Vision-Service-Token
pose_enabled=false
pose_provider=disabled_placeholder
pose_model_path=null
pose_fps=0.0
temporal_live_enabled=NO in the observed stable runtime
old_69_service_started=NO
real_post_sent=NO
```

Known stable validation before this branch:

```text
python -m pytest tests/test_capture_worker_replay.py -q
2 passed

python -m pytest tests/test_alerting_manual_send.py tests/test_fall_event_reporter_service.py tests/test_result_publisher_service.py tests/test_fall_alert_polling_api.py tests/test_end_to_end_pipeline.py -q
43 passed, 4 warnings

python -m pytest tests/test_stream_service_single_source.py -q
2 passed
```

GitHub checkpoint:

```text
branch: feature/new-pose-reintegration
tag: stable-demo-20260622-no-pose-dryrun
download zip: https://github.com/kangzhouyang/69-service-/archive/refs/tags/stable-demo-20260622-no-pose-dryrun.zip
```

## Qualification Goal

The future goal is to qualify a new pose/posture model before it can influence main-system fall alerts.

The word "post model" in this phase is interpreted as pose/posture model. Main-system POST alerting is handled only by the bridge reporter.

The pose model must pass staged qualification before it can affect fall decisions:

```text
raw video inventory
-> annotation standard
-> pseudo labels for human review
-> reviewed dataset build
-> shadow-only pose integration
-> offline pose quality evaluation
-> pose-assisted fall fusion training/evaluation
-> dry-run shadow runtime validation
-> controlled pose-assisted dry-run promotion
-> explicitly approved one-shot real POST only after all gates pass
```

## Non-Negotiable Safety Rules

Before complete evaluation passes:

```text
MAIN_SYSTEM_REPORT_DRY_RUN must remain true.
New pose output must not affect fallen_confirmed.
New pose output must not affect risk_level.
New pose output must not generate incident_id.
New pose output must not trigger reporter POST.
No real POST to the main system is allowed.
```

Explicitly forbidden until the relevant later stage:

```text
Do not disable MAIN_SYSTEM_REPORT_DRY_RUN.
Do not call /alerting/simulation/send-once for model accuracy evidence.
Do not start old 69-service.
Do not mix legacy 69 skeleton providers into production runtime.
Do not commit or print token values.
Do not treat unreviewed pseudo labels as training truth.
Do not treat training metrics as online production accuracy.
Do not allow one source video to appear in train/val/test simultaneously.
```

## Required Stage Gates

### Stage 1: Video Inventory

Inventory existing raw videos only. No training.

Expected outputs:

```text
datasets/pose_fall/raw_video_manifest_20260622.csv
datasets/pose_fall/raw_video_manifest_20260622.jsonl
```

### Stage 2: Annotation Guideline And Schema

Define video-level, clip-level, key-frame, bbox, and optional pose review standards before any labeling.

Expected outputs:

```text
docs/pose_fall_annotation_guideline_20260622.md
datasets/pose_fall/annotation_schema.json
```

Important caveat:

```text
Unreviewed pseudo labels are candidates only. They are not training labels.
```

### Stage 3: Pseudo Label And Review Tool

Generate candidates to accelerate human review. Stop if there is no human review.

Allowed script namespace:

```text
scripts/pose_fall/
```

Expected output directories:

```text
datasets/pose_fall/frames/
datasets/pose_fall/pseudo_labels/
datasets/pose_fall/reviewed_labels/
datasets/pose_fall/exports/
```

### Stage 4: Reviewed Dataset Build

Use only `reviewed=true` labels and split by `video_id`, not frame.

Expected outputs:

```text
datasets/pose_fall/splits/train.jsonl
datasets/pose_fall/splits/val.jsonl
datasets/pose_fall/splits/test.jsonl
datasets/pose_fall/dataset_card_20260622.md
```

### Stage 5: Pose Shadow-Only Integration

The pose model may load only in shadow-only mode.

Required safe config:

```text
ENABLE_POSE=true
POSE_PROVIDER=<new_pose_provider>
POSE_SHADOW_ONLY=true
POSE_USE_FOR_FALL=false
MAIN_SYSTEM_REPORT_DRY_RUN=true
```

If these settings do not exist yet, add them with safe defaults:

```text
POSE_SHADOW_ONLY=true
POSE_USE_FOR_FALL=false
```

### Stage 6: Offline Pose Quality Evaluation

Evaluate pose quality on the reviewed dataset. Do not train fall logic in this stage.

Minimum suggested gates:

```text
pose_detect_rate >= 90% on person-visible frames
bbox_alignment_rate >= 90%
latency p95 <= 120ms or fits current real-time budget
failure_rate <= 5%
```

### Stage 7: Pose-Assisted Fall Fusion Training

Train or tune a fall classifier/fusion module. Do not claim to train a pose estimator unless full keypoint labels exist.

Suggested production gate:

```text
test recall_fall >= 0.90
test precision_fall >= 0.90
false_positive_rate on nonfall <= 5%
critical false positives on sitting/lying/bending <= 3%
detection latency <= 2 seconds from impact to confirmed
no degradation versus current no-pose baseline on replay set
```

### Stage 8: Dry-Run Shadow Runtime Validation

Run replay comparison:

```text
current no-pose decision
pose-assisted shadow decision
disagreement
latency
fps
```

Real POST remains forbidden.

### Stage 9: Pose-Assisted Dry-Run Promotion

Only after Stages 6, 7, and 8 pass:

```text
POSE_USE_FOR_FALL=true
MAIN_SYSTEM_REPORT_DRY_RUN=true
```

The model may influence local fall decision, but real POST remains disabled.

### Stage 10: Controlled Real POST

Only after Stage 9 passes and the user explicitly approves:

```text
MAIN_SYSTEM_REPORT_DRY_RUN=false
```

Maximum one real POST attempt. Immediately restore:

```text
MAIN_SYSTEM_REPORT_DRY_RUN=true
```

### Stage 11: Final Handoff

Expected final document:

```text
docs/pose_model_alert_integration_final_handoff_20260622.md
```

It must include dataset source, annotation rules, dataset stats, model version, training/evaluation results, shadow-only result, dry-run result, real POST result if approved, known limits, rollback plan, and recommended runtime config.

## Rollback Config

If any gate fails, stay on the stable no-pose plan:

```text
MAIN_SYSTEM_REPORT_DRY_RUN=true
ENABLE_POSE=false
POSE_PROVIDER=disabled_placeholder
POSE_USE_FOR_FALL=false
```

Rollback command:

```powershell
git fetch origin --tags
git checkout stable-demo-20260622-no-pose-dryrun
```

## Stage 0 Status

```text
index_clean_at_stage_start=YES
isolated_branch_created=YES
stable_checkpoint_pushed=YES
qualification_not_started_beyond_stage0=YES
```

# Fall Temporal V6 Residual FN Training Plan

Date: 2026-07-04

Professor-facing runbook:

```text
docs/temporal_v6_professor_review_runbook_20260704.md
```

## Current State

The v6 temporal decision layer now reaches the initial recall gate on the 30-video fall review set:

```text
slow_fall_review_stride8:
TP = 21
FN = 9
FP = 0
fall_event_recall = 0.7000
duplicate_alarm_videos = []

fp_regression_stride8:
confirmed FP = 0 / 33
```

This means the next improvement stage should shift from adding state-machine fallbacks to building reviewed training data for the temporal model and posture/contact scorers.

## Residual FN Audit

Generated artifacts:

```text
evaluations/fall_temporal_v6/residual_fn_audit/temporal_v6_residual_fn_audit.json
evaluations/fall_temporal_v6/residual_fn_audit/temporal_v6_residual_fn_audit.md
data/temporal_v6_review/residual_fn_review_seed.jsonl
data/temporal_v6_review/residual_fn_review_seed_summary.json
```

Residual FN videos:

```text
fall-05.mp4
fall-08.mp4
fall-17.mp4
fall-18.mp4
fall-20.mp4
fall-21.mp4
fall-24.mp4
fall-25.mp4
fall-27.mp4
```

Current category split:

```text
detector_or_tracking_evidence_missing: 3
pose_or_low_posture_collapse_after_drop: 2
slow_or_normal_lying_ambiguous: 2
scene_or_pose_context_uncertain: 1
insufficient_multi_evidence_for_rules: 1
```

The review seed JSONL has one row per residual FN and is the file reviewers should edit first:

```text
data/temporal_v6_review/residual_fn_review_seed.jsonl
```

Default seed summary:

```text
row_count = 9
suggested confirmed_fall_train = 4
suggested confirmed_fall_but_detection_issue = 3
suggested ambiguous_second_review = 2
```

Before a row can be used for training, reviewers should:

```text
set review_status = reviewed (approved is still accepted for backward compatibility)
set usable_for_training = true when the event is valid for the target model
fill fall_start_ms / ground_contact_start_ms / low_posture_start_ms
set review_decision to the final human decision
add reviewer and review_notes
```

Build and validate the review seed:

```powershell
python scripts\build_temporal_v6_review_seed.py `
  --audit evaluations\fall_temporal_v6\residual_fn_audit\temporal_v6_residual_fn_audit.json `
  --output data\temporal_v6_review\residual_fn_review_seed.jsonl `
  --summary data\temporal_v6_review\residual_fn_review_seed_summary.json

python scripts\build_temporal_v6_review_packet.py `
  --output-dir data\temporal_v6_review\professor_review_packet

python scripts\validate_temporal_v6_review_seed.py `
  --input data\temporal_v6_review\residual_fn_review_seed.jsonl

python scripts\build_temporal_v6_training_dataset.py `
  --review data\temporal_v6_review\residual_fn_review_seed.jsonl `
  --sequences-dir data\temporal_sequences_phase6d `
  --output-dir data\temporal_v6_training\residual_reviewed

python scripts\build_temporal_v6_lstm_training_manifest.py `
  --output data\temporal_v6_training\lstm_v6_training_manifest.json
```

The validator is designed for a two-stage workflow:

```text
unreviewed seed rows:
  may keep event-time fields empty
  must remain usable_for_training = false

reviewed training rows:
  review_status must be reviewed or approved
  usable_for_training must be true
  review_decision must be confirmed_fall_train or hard_negative_train or confirmed_fall_but_detection_issue
  fall_start_ms / ground_contact_start_ms / low_posture_start_ms must be filled
  recovered_within_5s must be true or false
  scene_type / support_surface / occlusion_level must be reviewed, not unknown
  reviewer and review_notes must be filled
  ground_contact_start_ms, low_posture_start_ms, motion_end_ms, and recovery_start_ms cannot be before fall_start_ms
  confirmed_fall_but_detection_issue requires track_quality_issue=true or pose_quality_issue=true
```

The professor review packet contains:

```text
data/temporal_v6_review/professor_review_packet/residual_fn_review_sheet.csv
data/temporal_v6_review/professor_review_packet/residual_fn_review_packet.md
data/temporal_v6_review/professor_review_packet/frame_windows/*.csv
```

Current packet state:

```text
review_rows = 9
frame_window_csv_count = 9
missing_frame_files = []
window_ms = 1600
```

The CSV sheet is a reading aid, not the training source of truth. After review, update `data/temporal_v6_review/residual_fn_review_seed.jsonl`, then rerun validation and dataset generation.

If the professor edits the CSV review sheet first, apply it back to the JSONL source of truth with:

```powershell
python scripts\apply_temporal_v6_review_sheet.py --dry-run

python scripts\apply_temporal_v6_review_sheet.py
```

Current dry-run state before professor edits:

```text
seed_rows = 9
sheet_rows = 9
changed_count = 0
validation_error_count = 0
written = false
```

Blank CSV cells do not overwrite JSONL fields. This prevents an untouched review sheet from erasing seed metadata.

Recommended one-command post-review preparation:

```powershell
python scripts\run_temporal_v6_post_review_pipeline.py `
  --summary data\temporal_v6_training\post_review_pipeline_summary.json
```

Current pipeline state before professor edits:

```text
status = ok
reason = no_reviewed_residual_training_rows
ready_for_training = false
apply_review_sheet.changed_count = 0
review_validation.usable_for_training_count = 0
reviewed_training_dataset.trainable_review_rows = 0
lstm_training_manifest.residual_reviewed_input_count = 0
acceptance_gate.passed = false
acceptance_gate.slow_fall_recall = 0.70
```

After professor edits, rerun this pipeline first. If `ready_for_training=true`, continue to the LSTM training command below.

Master status command:

```powershell
python scripts\summarize_temporal_v6_status.py `
  --output evaluations\fall_temporal_v6\temporal_v6_master_status.json
```

Current master status:

```text
overall_status = in_progress
blocking_stage = post_review_training_data
review_packet.status = ready
post_review_training_data.status = waiting_for_review
candidate_eval.status = dry_run
acceptance.status = failed
promotion.status = not_ready
next_step = Complete professor/manual review, apply the sheet, and rerun the post-review pipeline.
```

The training dataset builder consumes only approved, trainable rows. It writes:

```text
data/temporal_v6_training/residual_reviewed/train_inputs.json
data/temporal_v6_training/residual_reviewed/dataset_summary.json
data/temporal_v6_training/residual_reviewed/<dataset>/<video>.jsonl
```

It also changes the frame labels from coarse video-level labels to event-time labels:

```text
frames before fall_start_ms -> label = non_fall
frames from fall_start_ms to motion_end_ms -> label = fall
frames after motion_end_ms -> label = non_fall
```

If `motion_end_ms` is empty, frames from `fall_start_ms` to the end of the sequence remain `fall`. This is useful for training the temporal model to distinguish the pre-fall approach, the falling transition, and the post-contact state instead of treating the whole video as one coarse positive label.

The LSTM training manifest then combines:

```text
base temporal sequence files:
  data/temporal_sequences_phase6d/gmdcsa24
  data/temporal_sequences_phase6d/ur_fall
  data/temporal_sequences_phase6d/ur_fall_cam1

approved residual reviewed files:
  data/temporal_v6_training/residual_reviewed
```

Current manifest state before professor approval:

```text
trainable_input_count = 167
residual_reviewed_input_count = 0
label_counts:
  fall = 2220
  non_fall = 4439
schema = fall_lstm_features_v1 / db4246cef1eb39a1
```

After professor approval, regenerate the residual reviewed dataset and this manifest before training. The new model must not be promoted unless these gates pass:

```text
slow_fall_review recall >= 0.80
fp_regression confirmed FP = 0
duplicate_alarm_videos = []
UR mini confirmed FP = 0
```

Training command from the manifest:

```powershell
python scripts\train_fall_lstm.py `
  --input-manifest data\temporal_v6_training\lstm_v6_training_manifest.json `
  --output-dir models `
  --model-version v6 `
  --epochs 20 `
  --stride 4
```

The training script records `trained_from_inputs` and `input_manifest` in the model metrics/config artifacts so a future `fall_lstm_v6.onnx` can be traced back to the exact reviewed input list.

Candidate model regression commands:

```powershell
python scripts\run_temporal_v6_regression_eval.py `
  --manifest evaluations\fall_temporal_v6\slow_fall_review_manifest.json `
  --output-dir evaluations\fall_temporal_v6\slow_fall_review_stride8_v6_lstm_candidate `
  --frame-stride 8 `
  --temporal-provider shadow `
  --temporal-model-path models\fall_lstm_v6.onnx `
  --temporal-schema-path models\fall_lstm_v6_features.json

python scripts\run_temporal_v6_regression_eval.py `
  --manifest evaluations\fall_temporal_v6\fp_regression_manifest.json `
  --output-dir evaluations\fall_temporal_v6\fp_regression_stride8_v6_lstm_candidate `
  --frame-stride 8 `
  --temporal-provider shadow `
  --temporal-model-path models\fall_lstm_v6.onnx `
  --temporal-schema-path models\fall_lstm_v6_features.json

python scripts\run_temporal_v6_regression_eval.py `
  --manifest evaluations\fall_temporal_v6\temporal_v6_ur_mini_manifest.json `
  --output-dir evaluations\fall_temporal_v6\ur_mini_regression_stride4_v6_lstm_candidate `
  --frame-stride 4 `
  --temporal-provider shadow `
  --temporal-model-path models\fall_lstm_v6.onnx `
  --temporal-schema-path models\fall_lstm_v6_features.json
```

Each comparison JSON records `temporal_runtime_config`, so candidate regression results remain traceable to the exact model and schema paths.

Recommended candidate evaluation pipeline after training:

```powershell
python scripts\run_temporal_v6_candidate_eval_pipeline.py `
  --model-path models\fall_lstm_v6.onnx `
  --schema-path models\fall_lstm_v6_features.json `
  --temporal-provider shadow `
  --dry-run `
  --summary evaluations\fall_temporal_v6\temporal_v6_candidate_eval_pipeline.json

python scripts\run_temporal_v6_candidate_eval_pipeline.py `
  --model-path models\fall_lstm_v6.onnx `
  --schema-path models\fall_lstm_v6_features.json `
  --temporal-provider shadow `
  --summary evaluations\fall_temporal_v6\temporal_v6_candidate_eval_pipeline.json
```

This runs the slow-fall, ADL hard-negative, and UR mini regressions, then checks the candidate comparison JSON files against the final acceptance gate.

Final promotion-readiness gate:

```powershell
python scripts\check_temporal_v6_promotion_readiness.py `
  --output evaluations\fall_temporal_v6\temporal_v6_promotion_readiness.json
```

Current promotion-readiness state:

```text
ready = false
model_exists = false
schema_exists = false
metrics_exists = false
train_config_exists = false
candidate_regression_completed = false
candidate_acceptance_passed = false
promotion_env = null
```

Do not change runtime environment variables to `fall_lstm_v6` until this gate returns `ready=true`.

After exporting and evaluating a candidate model, run the acceptance gate:

```powershell
python scripts\check_temporal_v6_acceptance.py `
  --output evaluations\fall_temporal_v6\temporal_v6_acceptance_gate.json
```

Current gate result before professor approval and retraining:

```text
passed = false
slow_fall_review_recall = 0.70, required >= 0.80
fp_regression_confirmed_false_positive = 0, required <= 0
duplicate_alarm_videos = []
ur_mini_confirmed_false_positive = 0, required <= 0
```

This means the implementation is safe enough to keep iterating, but the final effect is not complete until the reviewed residual data and/or trained temporal scorer lift the slow-fall review recall gate without breaking the false-positive and duplicate-alarm gates.

## Why Rules Should Stop Here

The remaining FN cases are no longer dominated by one missing threshold. Several cases have weak or collapsed evidence:

```text
low fall evidence
weak floor contact
weak impact proxy
missing low posture
short or absent low-posture hold
possible detector or tracking failure
slow-fall versus voluntary lying ambiguity
```

If the state machine is widened further, it will likely collide with ADL cases such as bending, picking objects, sitting, or normal lying. The correct next step is therefore:

```text
review -> label event timing and scene context -> train / calibrate temporal evidence -> rerun v6 gates
```

## Manual Review Instructions

For each residual FN video, the reviewer should inspect the original video and the corresponding frame metrics CSV.

Required labels:

```text
fall_start_ms
low_posture_start_ms
ground_contact_start_ms
motion_end_ms
recovery_start_ms
recovered_within_5s
support_surface
scene_type
occlusion_level
track_quality_issue
pose_quality_issue
fall_subtype
review_decision
review_notes
```

Recommended `fall_subtype` values:

```text
fast_fall
slow_fall
slide_to_floor
kneel_then_fall
fall_with_pose_collapse
fall_with_tracking_loss
ambiguous_needs_second_review
```

Recommended `review_decision` values:

```text
confirmed_fall_train
confirmed_fall_but_detection_issue
ambiguous_second_review
exclude_bad_tracking
exclude_not_fall
```

## Category-Specific Actions

### detector_or_tracking_evidence_missing

Videos:

```text
fall-18.mp4
fall-25.mp4
fall-27.mp4
```

Action:

```text
Do not add a fall-state rule.
Check whether person detection, track ID continuity, or pose extraction failed.
If the person is visibly falling, add these clips to detector/pose hard-recall training.
If the person is not reliably visible, mark exclude_bad_tracking.
```

### pose_or_low_posture_collapse_after_drop

Videos:

```text
fall-17.mp4
fall-21.mp4
```

Action:

```text
Review whether the person becomes low/grounded but pose features fail to express it.
Label fall_start_ms and ground_contact_start_ms.
Use these clips to train low-posture and floor-contact scorers.
Avoid widening vertical-drop-only rules because ADL picking/bending can look similar.
```

### slow_or_normal_lying_ambiguous

Videos:

```text
fall-05.mp4
fall-20.mp4
```

Action:

```text
Review whether the final low posture is true fall, voluntary lying, or dataset ambiguity.
Add explicit support_surface and floor_risk labels.
Use only confirmed true falls for slow-fall training.
If voluntary lying cannot be excluded, mark ambiguous_second_review.
```

### scene_or_pose_context_uncertain

Videos:

```text
fall-24.mp4
```

Action:

```text
Review scene context, occlusion, and pose quality.
If a person is only partially visible, mark occlusion_level and pose_quality_issue.
Use this as a scene-context or pose robustness training sample.
```

### insufficient_multi_evidence_for_rules

Videos:

```text
fall-08.mp4
```

Action:

```text
Keep as a hard-recall training sample.
Do not add a new rule until manual labels prove a stable post-fall interval or ground contact.
```

## Training Dataset Shape

The next temporal training dataset should be clip-level plus event-time labeled. A single row should represent one reviewed event window.

Example:

```json
{
  "video_id": "ur_fall/fall-21.mp4",
  "label": "fall",
  "fall_subtype": "fall_with_pose_collapse",
  "expected_alarm": true,
  "fall_start_ms": 1280,
  "ground_contact_start_ms": 1600,
  "low_posture_start_ms": 1600,
  "motion_end_ms": 1920,
  "recovered_within_5s": false,
  "support_surface": "none",
  "scene_type": "floor_risk_zone",
  "occlusion_level": "medium",
  "track_quality_issue": false,
  "pose_quality_issue": true,
  "review_decision": "confirmed_fall_train",
  "review_notes": "Strong drop, low-posture scorer failed after contact."
}
```

Seed generation command:

```text
python scripts/build_temporal_v6_residual_audit.py --comparison evaluations/fall_temporal_v6/slow_fall_review_stride8/temporal_v6_regression_comparison.json --manifest evaluations/fall_temporal_v6/slow_fall_review_manifest.json --frames-dir evaluations/fall_temporal_v6/slow_fall_review_stride8/v6_decision --output-dir evaluations/fall_temporal_v6/residual_fn_audit

python scripts/build_temporal_v6_review_seed.py --audit evaluations/fall_temporal_v6/residual_fn_audit/temporal_v6_residual_fn_audit.json --output data/temporal_v6_review/residual_fn_review_seed.jsonl --summary data/temporal_v6_review/residual_fn_review_seed_summary.json
```

## Acceptance Gates For The Next Iteration

After review and training/calibration, rerun:

```text
python scripts/run_temporal_v6_regression_eval.py --manifest evaluations/fall_temporal_v6/slow_fall_review_manifest.json --output-dir evaluations/fall_temporal_v6/slow_fall_review_stride8 --frame-stride 8

python scripts/run_temporal_v6_regression_eval.py --manifest evaluations/fall_temporal_v6/fp_regression_manifest.json --output-dir evaluations/fall_temporal_v6/fp_regression_stride8 --frame-stride 8

python -m pytest -q
```

Target gates:

```text
slow_fall_review recall >= 0.80
ADL confirmed FP = 0 / 33
duplicate_alarm_videos = []
full pytest passes
```

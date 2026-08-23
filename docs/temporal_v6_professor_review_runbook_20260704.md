# Temporal V6 Professor Review Runbook

Date: 2026-07-04

## 1. Current Decision

The temporal v6 logic is implemented and guarded, but final acceptance is not complete.

Current master status:

```text
overall_status = in_progress
blocking_stage = post_review_training_data
review_packet.status = ready
post_review_training_data.status = waiting_for_review
candidate_eval.status = dry_run
acceptance.status = failed
promotion.status = not_ready
```

Current measured gate:

```text
slow_fall_review recall = 0.70
required recall = 0.80
ADL confirmed false positives = 0
duplicate alarms = 0
```

This means the system is guarded against the main ADL false-positive cases, but the remaining slow-fall recall work requires professor/manual review before model training.

## 2. What The Professor Should Review

Open the review packet:

```text
data/temporal_v6_review/professor_review_packet/residual_fn_review_sheet.csv
data/temporal_v6_review/professor_review_packet/residual_fn_review_packet.md
data/temporal_v6_review/professor_review_packet/frame_windows/*.csv
```

There are 9 residual false-negative videos:

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

The professor should decide whether each case is:

```text
confirmed_fall_train
confirmed_fall_but_detection_issue
hard_negative_train
exclude_uncertain
```

## 3. Fields To Fill

For a row that should enter training:

```text
review_status = reviewed (approved is also accepted for backward compatibility)
usable_for_training = true
review_decision = confirmed_fall_train / hard_negative_train
fall_start_ms = required
ground_contact_start_ms = required
low_posture_start_ms = required
motion_end_ms = optional but recommended
recovery_start_ms = optional
recovered_within_5s = true or false
scene_type = reviewed value, not unknown
support_surface = reviewed value, not unknown
occlusion_level = reviewed value, not unknown
reviewer = reviewer name
review_notes = short evidence note
```

For uncertain or bad cases:

```text
review_status = reviewed
usable_for_training = false
review_decision = exclude_uncertain
reviewer = reviewer name
review_notes = reason for exclusion or second review
```

For `confirmed_fall_but_detection_issue`:

```text
Do not mark it trainable directly unless the detector/tracking/pose issue is explicitly confirmed.
If it must remain trainable, keep track_quality_issue=true or pose_quality_issue=true and explain the issue in review_notes.
```

Blank CSV cells do not overwrite the JSONL source of truth.

## 4. Apply The Review

After editing the CSV sheet, run:

```powershell
python scripts\apply_temporal_v6_review_sheet.py --dry-run
python scripts\apply_temporal_v6_review_sheet.py
```

Then run the post-review pipeline:

```powershell
python scripts\run_temporal_v6_post_review_pipeline.py `
  --summary data\temporal_v6_training\post_review_pipeline_summary.json
```

The key field is:

```text
ready_for_training
```

If it is `false`, fix the review labels first.

If it is `true`, continue to training.

## 5. Train Candidate LSTM V6

Use the generated manifest:

```powershell
python scripts\train_fall_lstm.py `
  --input-manifest data\temporal_v6_training\lstm_v6_training_manifest.json `
  --output-dir models `
  --model-version v6 `
  --epochs 20 `
  --stride 4
```

Expected candidate artifacts:

```text
models/fall_lstm_v6.onnx
models/fall_lstm_v6_features.json
models/fall_lstm_v6_metrics.json
models/fall_lstm_v6_train_config.json
models/fall_lstm_v6_threshold_calibration.json
```

## 6. Evaluate Candidate Model

First dry-run the commands:

```powershell
python scripts\run_temporal_v6_candidate_eval_pipeline.py `
  --model-path models\fall_lstm_v6.onnx `
  --schema-path models\fall_lstm_v6_features.json `
  --temporal-provider shadow `
  --dry-run `
  --summary evaluations\fall_temporal_v6\temporal_v6_candidate_eval_pipeline.json
```

Then run the actual evaluation:

```powershell
python scripts\run_temporal_v6_candidate_eval_pipeline.py `
  --model-path models\fall_lstm_v6.onnx `
  --schema-path models\fall_lstm_v6_features.json `
  --temporal-provider shadow `
  --summary evaluations\fall_temporal_v6\temporal_v6_candidate_eval_pipeline.json
```

This runs:

```text
slow_fall_review
fp_regression hard negatives
UR mini regression
acceptance gate
```

## 7. Promotion Gate

Do not promote based only on model existence.

Run:

```powershell
python scripts\check_temporal_v6_promotion_readiness.py `
  --output evaluations\fall_temporal_v6\temporal_v6_promotion_readiness.json
```

Only promote if:

```text
ready = true
```

The gate requires:

```text
model artifact exists
schema exists
metrics exists
train config exists
trained_from_inputs is recorded
ONNX validation passed
candidate regression completed
candidate acceptance passed
```

## 8. Final Status Check

At any time, run:

```powershell
python scripts\summarize_temporal_v6_status.py `
  --output evaluations\fall_temporal_v6\temporal_v6_master_status.json
```

The target final state is:

```text
overall_status = complete
blocking_stage = null
review_packet.passed = true
post_review_training_data.passed = true
candidate_eval.passed = true
acceptance.passed = true
promotion.passed = true
```

Until then, the work is not complete.

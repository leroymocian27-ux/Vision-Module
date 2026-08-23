# Phase 6 LSTM Dataset Training Report

## Dataset Selection

Selected first-pass dataset:

- UR Fall Detection Dataset
- Phase 6B smoke training subset: 8 fall videos and 12 ADL videos
- Local videos: `datasets/ur_fall/videos`
- Manifest: `datasets/dataset_manifest.json`

Reason:

- The official UR Fall page provides direct RGB zip archives.
- Labels are clear from sequence names: `fall-*` and `adl-*`.
- The dataset includes 30 fall and 40 activities of daily living sequences, enough to run the first engineering loop.
- License is Creative Commons Attribution-NonCommercial-ShareAlike 4.0, so this first model is suitable for research/demo validation, not commercial deployment.

Phase 6C download status:

- UR Fall full RGB set is now available locally: 30 fall videos and 40 ADL videos.
- The generated Phase 6 label manifest has 70 rows.
- UR Fall ADL files are still `unknown_adl` and `usable_for_training=false` until subtype review assigns sitting, bending, squatting, picking_object, lying_down_normal, walking, or standing.
- The full UR Fall download expands the data pool, but it does not by itself make v2 promotable.

Other datasets considered:

- Multiple Cameras Fall Dataset: useful for future multi-view validation, but the official page is currently protected and public mirrors such as Kaggle may require credentials.
- UP-Fall: useful but too large for first-pass automation and not appropriate for a quick local training loop.

## Export

Command:

```powershell
C:\Users\YANG\.conda\envs\torchgpu\python.exe scripts\export_dataset_temporal_sequences.py `
  --dataset ur_fall `
  --frame-stride 3 `
  --max-frames 220
```

Output:

- `data/temporal_sequences/ur_fall/*.jsonl`
- Schema: `fall_lstm_features_v1`
- Feature dim: 15
- Window size: 32
- Schema hash: `db4246cef1eb39a1`

Pose was intentionally disabled for this first model to avoid YOLO-pose environment instability. The model uses bbox and motion features only.

## Training

Command:

```powershell
$files = Get-ChildItem -Path data\temporal_sequences\ur_fall -Filter *.jsonl | ForEach-Object { $_.FullName }
C:\Users\YANG\.conda\envs\torchgpu\python.exe scripts\train_fall_lstm.py `
  --input $files `
  --output-dir models `
  --epochs 20 `
  --batch-size 16 `
  --stride 2
```

Output artifacts:

- `models/fall_lstm.onnx`
- `models/fall_lstm_features.json`
- `models/fall_lstm_metrics.json`
- `models/train_config.json`
- `models/threshold_calibration.json`

Training summary:

```json
{
  "samples": 186,
  "positive_samples": 31,
  "negative_samples": 155,
  "last_loss": 0.534587,
  "onnx_validation": {
    "passed": true,
    "max_abs_diff": 5.960464477539063e-08
  }
}
```

## Runtime Smoke Test

`TEMPORAL_MODEL_PROVIDER=onnx_lstm` loaded `models/fall_lstm.onnx` successfully.

After 32 frames:

```json
{
  "source": "onnx_lstm",
  "window_ready": true,
  "model_loaded": true,
  "fallback_active": false
}
```

## Evaluation

Evaluation configuration:

```text
ENABLE_POSE=false
dataset=ur_fall
normal=12
fall=8
frame_stride=5
max_frames=220
```

Mock baseline:

```json
{
  "adl_confirmed_fp": 0,
  "adl_candidate_fp": 0,
  "fall_falling_recall": 0.5,
  "fall_confirmed_recall": 0.0,
  "fall_detected": 4,
  "fall_missed": 4
}
```

ONNX LSTM:

```json
{
  "adl_confirmed_fp": 0,
  "adl_candidate_fp": 0,
  "fall_falling_recall": 0.5,
  "fall_confirmed_recall": 0.0,
  "fall_detected": 4,
  "fall_missed": 4
}
```

Shadow mode:

```json
{
  "adl_confirmed_fp": 0,
  "adl_candidate_fp": 0,
  "fall_falling_recall": 0.5,
  "fall_confirmed_recall": 0.0,
  "fall_detected": 4,
  "fall_missed": 4
}
```

## Conclusion

The full engineering loop is now complete:

```text
public dataset -> automatic labels -> feature export -> LSTM train -> ONNX export -> runtime load -> fallback/shadow -> offline evaluation
```

This first ONNX model does not yet outperform the mock baseline on recall. It also does not increase ADL confirmed false positives. Therefore the recommended runtime mode is:

```text
TEMPORAL_MODEL_PROVIDER=shadow
```

Do not promote `onnx_lstm` as the active state-machine provider until additional ADL subtype data and more fall samples prove improvement over the Phase 5 mock baseline.

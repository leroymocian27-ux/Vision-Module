# Phase 9 Full Accuracy Closure Report

Generated: `2026-06-08T07:27:50.605775+00:00`

## Decision

- target: end-to-end fall alarm recall >= 0.80
- current e2e recall: 1.0
- ADL confirmed FP: 0
- decision: `live_loop_passed_but_not_certified_80_percent`

## Selected Runtime

- `YOLO_FALL_MODEL_PATH=models/yolo_fall_detector_phase9_selected.pt`
- `ENABLE_POSE=true`
- `POSE_PROVIDER=yolo`
- `ENABLE_TEMPORAL=true`
- `TEMPORAL_MODEL_PROVIDER=shadow`
- `TEMPORAL_ONNX_MODEL_PATH=models/fall_lstm_v5.onnx`
- `TEMPORAL_FEATURE_SCHEMA_PATH=models/fall_lstm_v5_features.json`
- `MAIN_SYSTEM_ALERT_ENABLED=true`
- `MAIN_SYSTEM_BASE_URL=http://127.0.0.1:8000/api/v1`
- `VISION_SERVICE_PUBLIC_BASE_URL=http://127.0.0.1:8001`

## Notes

- Do not promote to default production unless frozen e2e acceptance passes.

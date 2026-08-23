# Release Notes

Version: `fall-monitor-stable-v1.0-rc`
Date: 2026-07-20

## Scope

This release candidate freezes the current fall-monitoring system for stabilization and packaging. It focuses on repeatable startup, safe defaults, observable runtime state, and local smoke validation.

## Included

- Stable runtime profiles: `safe_demo`, `dev_experiment`, `production_candidate`
- Config validation with model path and SHA256 checks
- Safe demo startup, stop, status, and smoke scripts
- S2 startup/shutdown/process stability gate
- S3 camera/video stream resilience gate
- S4 AI pipeline resilience tests and contracts
- S5 unified status/degradation contract
- `/healthz`, `/status`, latest frame, and latest integration result smoke coverage
- Robot Assist, Go2 control, Qwen/VLM, and real delivery disabled by default

## Validation

- `PASS` config validation for all three profiles
- `PASS` safe demo smoke: `artifacts/stable_smoke/20260720T021030Z/summary.json`
- `PASS` S2 startup/shutdown gate: `artifacts/stabilization/S2_STARTUP_SHUTDOWN_AND_PROCESS_STABILITY/20260720T023159Z/summary.json`
- `PASS` S3 camera stream gate: `artifacts/stabilization/S3_CAMERA_AND_VIDEO_STREAM_RESILIENCE/20260720T025317Z/summary.json`
- `PASS` S4 directed AI pipeline tests: `tests/stabilization/test_pose_disabled.py`, `test_temporal_warmup.py`, `test_inference_exception.py`, `test_pipeline_backpressure.py`, `test_frame_alignment.py`
- `PASS` S5 unified status tests: `artifacts/stabilization/S5_UNIFIED_STATUS_AND_DEGRADATION/20260720T112230/summary.json`

## Not Validated

- Real RTSP runtime
- Real RTSP reconnect runtime
- Synthetic fall event and event evidence package
- WebSocket contract
- Browser visual check
- Real event delivery
- S2 extended 10-cycle restart check

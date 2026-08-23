# Stabilization Execution Log

## 2026-07-20

Initial implementation of the stabilization framework:

- Added stable runtime profiles under `configs/`
- Added `scripts/validate_config.py`
- Added `scripts/run_stable_smoke.py`
- Added startup helper scripts
- Added S0/S1 baseline docs under `docs/stabilization/`

Pending validation:

- Run config validation for all profiles
- Run stable smoke with `safe_demo`
- Decide whether `/status` needs schema additions for startup phase and degradation summary

Validation update:

- `PASS` `python -m py_compile app\contracts\integration_v1.py app\events\qwen_keyframe.py scripts\validate_config.py scripts\run_stable_smoke.py`
- `PASS` `python scripts\validate_config.py --profile safe_demo --json-out artifacts\stabilization\validate_safe_demo.json`
- `PASS` `python scripts\validate_config.py --profile dev_experiment --json-out artifacts\stabilization\validate_dev_experiment.json`
- `PASS` `python scripts\validate_config.py --profile production_candidate --json-out artifacts\stabilization\validate_production_candidate.json`
- `PASS` `python scripts\run_stable_smoke.py --profile safe_demo --port 8010`
- `PASS` `powershell -ExecutionPolicy Bypass -File scripts\build_release_bundle.ps1`

Evidence paths:

- `artifacts\stabilization\validate_safe_demo.json`
- `artifacts\stabilization\validate_dev_experiment.json`
- `artifacts\stabilization\validate_production_candidate.json`
- `artifacts\stable_smoke\20260720T021030Z\summary.json`
- `artifacts\stable_smoke\20260720T021030Z\summary.md`
- `artifacts\stable_smoke\20260720T021030Z\status.json`
- `artifacts\stable_smoke\20260720T021030Z\latest-frame.jpg`
- `artifacts\releases\fall-monitor-stable-v1.0-rc_20260720_101541\release_manifest.json`

Fixes made during validation:

- Fixed Python 3.9 runtime type-alias compatibility in `app\events\qwen_keyframe.py`.
- Fixed Python 3.9/Pydantic optional-field compatibility in `app\contracts\integration_v1.py`.

Remaining validation boundary:

- WebSocket contract, synthetic fall event, incident evidence package, delivery outbox, and browser visual check remain `NOT_RUN`.
- `production_candidate` remains config-valid but emits a warning until a real RTSP URL is provided through a secure process environment.

S2 startup/shutdown/process stability update:

- `PASS` `python -m py_compile scripts\process_cleanup_check.py scripts\run_startup_shutdown_gate.py`
- `PASS` `python -m pytest tests\stabilization\test_process_cleanup_check.py -q`
- `PASS` `python scripts\run_startup_shutdown_gate.py --profile safe_demo --port 8012 --cycles 3`
- `PASS` `powershell -ExecutionPolicy Bypass -File scripts\build_release_bundle.ps1`

S2 evidence paths:

- `artifacts\stabilization\S2_STARTUP_SHUTDOWN_AND_PROCESS_STABILITY\20260720_102843\git_status_before.txt`
- `artifacts\stabilization\S2_STARTUP_SHUTDOWN_AND_PROCESS_STABILITY\20260720T023159Z\summary.json`
- `artifacts\stabilization\S2_STARTUP_SHUTDOWN_AND_PROCESS_STABILITY\20260720T023159Z\summary.md`
- `artifacts\stabilization\S2_STARTUP_SHUTDOWN_AND_PROCESS_STABILITY\20260720T023159Z\cycle_01\status.json`
- `artifacts\stabilization\S2_STARTUP_SHUTDOWN_AND_PROCESS_STABILITY\20260720T023159Z\cycle_02\status.json`
- `artifacts\stabilization\S2_STARTUP_SHUTDOWN_AND_PROCESS_STABILITY\20260720T023159Z\cycle_03\status.json`
- `artifacts\releases\fall-monitor-stable-v1.0-rc_20260720_103444\release_manifest.json`

S2 boundary:

- Real RTSP startup/shutdown remains `NOT_RUN`.
- Synthetic fall event, incident evidence package, WebSocket contract, and browser visual check remain `NOT_RUN`.
- Robot Assist, Go2 control, Qwen/Ollama VLM advisory, real event Delivery, and real main-system POST remain `NOT_IN_SCOPE`.

S3 camera/video stream resilience update:

- `PASS` `python -m py_compile scripts\run_camera_stream_gate.py app\camera\frame_freshness.py app\camera\frame_buffer.py app\camera\capture_worker.py app\camera\subprocess_capture_worker.py app\camera\source_manager.py app\camera\reconnect_policy.py app\api\rest_api.py app\services\status_service.py app\schemas\status.py app\schemas\stream.py`
- `PASS` individual S3 stabilization test files under `tests\stabilization\`
- `PASS` `python -m pytest tests\stabilization -q --maxfail=1`
- `PASS` `python scripts\run_camera_stream_gate.py --profile safe_demo --port 8013`
- `PASS` `powershell -ExecutionPolicy Bypass -File scripts\build_release_bundle.ps1`

S3 evidence paths:

- `artifacts\stabilization\S3_CAMERA_AND_VIDEO_STREAM_RESILIENCE\20260720_104131\git_status_before.txt`
- `artifacts\stabilization\S3_CAMERA_AND_VIDEO_STREAM_RESILIENCE\20260720T025317Z\summary.json`
- `artifacts\stabilization\S3_CAMERA_AND_VIDEO_STREAM_RESILIENCE\20260720T025317Z\summary.md`
- `artifacts\stabilization\S3_CAMERA_AND_VIDEO_STREAM_RESILIENCE\20260720T025317Z\config_snapshot.json`
- `artifacts\stabilization\S3_CAMERA_AND_VIDEO_STREAM_RESILIENCE\20260720T025317Z\status_snapshots\`
- `artifacts\stabilization\S3_CAMERA_AND_VIDEO_STREAM_RESILIENCE\20260720T025317Z\latest_frame_headers\`
- `artifacts\stabilization\S3_CAMERA_AND_VIDEO_STREAM_RESILIENCE\20260720T025317Z\test_results\`
- `artifacts\stabilization\S3_CAMERA_AND_VIDEO_STREAM_RESILIENCE\20260720T025317Z\fault_scenarios\`
- `artifacts\stabilization\S3_CAMERA_AND_VIDEO_STREAM_RESILIENCE\20260720T025317Z\process_cleanup.json`
- `artifacts\releases\fall-monitor-stable-v1.0-rc_20260720_105546\release_manifest.json`

S3 boundary:

- Real RTSP acceptance remains `NOT_RUN`.
- Real RTSP reconnect acceptance remains `NOT_RUN`.
- S2 extended 10-cycle restart check remains `NOT_RUN` and is deferred to RC freeze checks.
- Robot Assist, Go2 control, Qwen/Ollama VLM advisory, real event Delivery, and real main-system POST remain `NOT_IN_SCOPE`.

# Vision Service Stable Demo Handoff - 2026-06-22

## 1. Checkpoint Summary

This checkpoint captures the current stable demo state of the Vision Service. It is intended as a rollback point and as a handoff package for the next engineer.

Recommended checkpoint name:

```text
stable-demo-20260622-no-pose-dryrun
```

Current safe operating mode:

```text
MAIN_SYSTEM_REPORT_DRY_RUN=true
MAIN_SYSTEM_BASE_URL=http://192.168.8.254:8000/api/v1
MAIN_SYSTEM_FALL_EVENT_PATH=/video-bridge/fall-events
MAIN_SYSTEM_ALERT_TOKEN_HEADER=X-Vision-Service-Token
ENABLE_POSE=false
POSE_PROVIDER=disabled_placeholder
YOLO_POSE_MODEL_PATH is not loaded in runtime
ENABLE_TEMPORAL=false in the observed live runtime
```

Important security rule: do not commit `.env`, logs, model weights, datasets, camera recordings, or real bridge tokens. The repo now ignores `artifacts/`, `video/`, `models/rtmpose/`, `logs/`, datasets, runs, and weight formats.

## 2. What The System Does Today

The service is a standalone FastAPI-based realtime vision service for an elderly-care fall detection demo.

Main runtime capabilities:

- Starts a camera stream from RTSP, local file replay, or mock source.
- Captures frames through the camera source manager and capture workers.
- Runs person detection using Ultralytics YOLO.
- Runs dedicated fall-object detection using a separate YOLO fall detector.
- Tracks people and selected targets through the tracking pipeline.
- Builds motion, bbox, and local fall evidence without requiring pose.
- Publishes realtime results to the frontend through WebSocket and polling APIs.
- Streams live video through WebRTC.
- Generates local fall events with `incident_id`, `event_type=fall_confirmed`, and `risk_level=critical` when confirmation criteria are met.
- Sends bridge events through `FallEventReporterService`, but the current local/default validation mode is dry-run, so real HTTP POST is skipped.
- Provides a frontend demo with canvas overlay, target box rendering, status panels, WebRTC/WebSocket indicators, polling alert display, and a selected-target rainbow frame.

The current demo baseline is deliberately no-pose:

- Pose runtime is disabled.
- The service reports `pose_provider=disabled_placeholder`.
- Placeholder payloads can keep schemas stable, but no YOLO pose weights are loaded.
- No skeleton provider from the old `69-service` was added to production runtime.

## 3. Runtime Flow

Current no-pose fall detection path:

```text
Camera or local replay source
-> CaptureWorker / CameraSourceManager
-> FrameBuffer
-> DetectionService
-> YOLO person detector
-> YOLO fall detector
-> TrackingService / tracking worker
-> ResultPublisherService
-> bbox and motion feature fusion
-> fall candidate / confirmed fall logic
-> incident_id and local fall event payload
-> RealtimeResultStore
-> WebSocket / polling / frontend overlay
-> FallEventReporterService
-> dry-run guard skips real POST
```

Bridge target loaded in the current safe mode:

```text
http://192.168.8.254:8000/api/v1/video-bridge/fall-events
```

Header name:

```text
X-Vision-Service-Token
```

The token value is intentionally not documented and must stay in local environment configuration only.

## 4. Main Files And Responsibilities

Backend application:

- `app/main.py`: FastAPI app assembly and service wiring.
- `app/core/config.py`: environment-backed settings, including bridge, pose, temporal, detection, and stream flags.
- `app/camera/*`: camera source runtime, capture workers, local-file replay, and frame buffers.
- `app/detection/*`: person detection and fall-object detection.
- `app/services/stream_service.py`: starts a single authoritative source for capture, display, detection, tracking, and snapshots.
- `app/services/detection_service.py`: runs detection workers and records detector statistics.
- `app/services/tracking_service.py` and tracking workers: target tracking state and track ids.
- `app/services/result_publisher_service.py`: merges detection, tracking, pose placeholder, temporal/fall evidence, alert preview, and realtime result publishing.
- `app/services/fall_event_reporter_service.py`: builds bridge payloads, manages incident reuse/cooldown, and performs the dry-run guard before HTTP POST.
- `app/services/alert_simulator_service.py`: controlled manual simulation path. Do not use it unless explicitly approved.
- `app/services/status_service.py`: `/status` payload, including no-pose runtime diagnostics.
- `app/pose/placeholders.py`: no-pose placeholder helpers and runtime enable/disable checks.
- `app/temporal/*`: temporal feature/window/state-machine modules. They exist and are tested, but the observed stable demo runtime is not enabling temporal live.

Frontend:

- `frontend_demo/index.html`: demo page shell. The RTSP default is sanitized to `YOUR_PASSWORD`.
- `frontend_demo/app.js`: WebRTC, WebSocket, status polling, frontend state, and manual alert controls.
- `frontend_demo/overlay.js`: canvas overlay. Current visual enhancement adds a rainbow target frame only when `object.is_target === true`.
- `frontend_demo/styles.css`: panel and overlay styling.

Tests:

- `tests/test_alerting_manual_send.py`
- `tests/test_fall_event_reporter_service.py`
- `tests/test_result_publisher_service.py`
- `tests/test_fall_alert_polling_api.py`
- `tests/test_end_to_end_pipeline.py`
- `tests/test_capture_worker_replay.py`
- pose provider and stream single-source tests are present for future work, but pose remains disabled in the stable demo baseline.

## 5. Problems Found And How They Were Solved

### 5.1 Bridge Target Mismatch

Problem:

The local bridge target had drifted to `.253`, while the main system receiver record expected:

```text
http://192.168.8.254:8000/api/v1/video-bridge/fall-events
```

Solution:

The bridge target config was synced to:

```text
MAIN_SYSTEM_BASE_URL=http://192.168.8.254:8000/api/v1
MAIN_SYSTEM_FALL_EVENT_PATH=/video-bridge/fall-events
MAIN_SYSTEM_ALERT_TOKEN_HEADER=X-Vision-Service-Token
```

### 5.2 Runtime Was Still Trying To Use Pose

Problem:

Historical local configuration enabled:

```text
ENABLE_POSE=true
POSE_PROVIDER=yolo
```

That could accidentally load `yolov8n-pose.pt` or make the demo look like a production skeleton integration.

Solution:

The stable baseline is:

```text
ENABLE_POSE=false
POSE_PROVIDER=disabled_placeholder
```

The pose worker skips startup in placeholder mode. `/status` reports:

```text
pose_enabled=false
pose_provider=disabled_placeholder
pose_model_path=null
pose_fps=0.0
```

### 5.3 Dry Validation Accidentally Sent Real POST

Problem:

During dry validation, the live `fall_event_reporter` automatically sent a real POST and logged a successful report. That made no-real-POST validation unsafe.

Solution:

Added reporter dry-run guard:

```text
MAIN_SYSTEM_REPORT_DRY_RUN=true
```

When enabled, the reporter builds local events and status, but does not call HTTP POST. It records `dry_run_skipped` / `fall_event_report_dry_run skipped_real_post` style evidence without logging token values.

### 5.4 Controlled One-Shot Real Bridge Test

Problem:

The main system needed proof that one real bridge POST could be accepted, but live reporter must not stay in real-post mode.

Solution:

Temporarily disabled dry-run once, called the controlled send path exactly once, confirmed the main system accepted and pushed the event, then immediately restored:

```text
MAIN_SYSTEM_REPORT_DRY_RUN=true
```

Post-restore validation showed no continued real POST.

### 5.5 No-Pose Fall Replay Demo

Problem:

The team needed visible evidence that no-pose mode can still produce a local fall event through the detection/tracking/reporting chain.

Solution:

Used local-file replay with `CaptureWorker` FPS throttle at 2.0 FPS. The validated path was:

```text
local fall video
-> CaptureWorker local file source
-> 2.0 FPS throttle
-> detection_service
-> person detected
-> fall candidate detected
-> tracking track_id=1
-> fallen_confirmed
-> fall_confirmed event
-> risk_level=critical
-> incident_id generated
-> WebSocket observed
-> polling alert observed
-> reporter dry-run skipped_real_post
-> no real POST
```

### 5.6 Frontend Stability And Overlay

Problem:

The demo frontend needed a clearer selected-target visual without changing backend logic.

Solution:

`frontend_demo/overlay.js` now draws a rainbow thick frame only in the target branch:

```text
object.is_target === true
```

Ordinary detection boxes, bbox coordinates, risk labels, fall state, incident logic, pose guard logic, and backend behavior are unchanged.

## 6. Frameworks And Libraries

Backend:

- Python
- FastAPI
- Uvicorn
- Pydantic
- OpenCV capture backends
- Ultralytics YOLO for person and fall-object detection
- ByteTrack-style tracking integration
- WebSocket for result events
- WebRTC through the service streaming layer
- pytest / unittest for regression tests

Frontend:

- Plain HTML/CSS/JavaScript
- WebRTC browser APIs
- WebSocket browser APIs
- Canvas 2D overlay

Optional/future pose experiments:

- Ultralytics YOLO pose
- YOLO11 legacy pose adapters
- RTMPose / RTMPose ONNX
- MMPose/OpenMMLab stack

These are not enabled in the stable demo baseline.

## 7. Current Validation Evidence

Latest known stable validation:

```text
node --check frontend_demo/overlay.js: PASS
tests/test_capture_worker_replay.py: 2 passed
tests/test_alerting_manual_send.py
tests/test_fall_event_reporter_service.py
tests/test_result_publisher_service.py
tests/test_fall_alert_polling_api.py
tests/test_end_to_end_pipeline.py: 43 passed, 4 warnings
```

Runtime status observed before checkpoint:

```text
service_status=running
bridge endpoint=http://192.168.8.254:8000/api/v1/video-bridge/fall-events
fall_event_reporter.last_post_status=dry_run_skipped
alerting dry_run=true
pose_enabled=false
pose_provider=disabled_placeholder
pose_model_path=null
pose_fps=0.0
temporal.enabled=false in observed live runtime
```

Frontend smoke observed:

```text
demo page opened
WebRTC connected in previous smoke
WebSocket connected in previous smoke
console errors=0
target was not available in the live camera frame during rainbow-frame smoke
```

## 8. How To Run Safely

Install dependencies:

```powershell
cd D:\Program\vision_service
python -m pip install -r requirements.txt
```

Local/default safe validation:

```text
MAIN_SYSTEM_REPORT_DRY_RUN=true
ENABLE_POSE=false
POSE_PROVIDER=disabled_placeholder
```

Start service:

```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open demo:

```text
http://127.0.0.1:8000/demo
```

Start current camera through helper:

```powershell
$env:CAMERA_RTSP_PASSWORD="YOUR_PASSWORD"
python scripts/start_current_camera.py --host 192.168.8.252 --api-port 8000 --no-wait
```

Do not use `/alerting/simulation/send-once` unless the owner explicitly approves a real or controlled simulation test.

## 9. Tests To Re-run

Stable demo regression set:

```powershell
python -m pytest tests/test_capture_worker_replay.py -q
python -m pytest tests/test_alerting_manual_send.py tests/test_fall_event_reporter_service.py tests/test_result_publisher_service.py tests/test_fall_alert_polling_api.py tests/test_end_to_end_pipeline.py -q
```

Broader fall/stream/pose-adapter confidence checks:

```powershell
python -m pytest tests -q -k "fall or temporal or state_machine or result_publisher or stream or camera"
```

## 10. Known Caveats

- Real model weights are not included in the GitHub checkpoint. They remain local artifacts and are ignored by Git.
- Local replay videos and screenshots are not included in the GitHub checkpoint.
- `.env` is not included. Engineers must create their own local `.env` from `.env.example`.
- The stable demo is no-pose. Skeleton visualization is not expected.
- Temporal modules exist and have tests, but the observed safe live runtime reports `temporal.enabled=false`.
- The old `69-service` was not started and was not migrated as a production skeleton provider.
- The one-shot real bridge POST was completed earlier and should not be repeated casually.
- The frontend has a manual alert simulation button. Do not click it during dry-run validation unless the test plan explicitly allows it.

## 11. What Is Being Solved Next

The current system is good enough for a stable local/frontend demo and bridge dry-run verification. The next engineering themes are:

- Improve fall precision without enabling pose by default.
- Decide whether to formalize or remove experimental pose providers.
- Separate production-safe no-pose baseline from future pose research branches.
- Make replay/demo evidence reproducible without relying on local-only videos.
- Add clearer UI state for target availability and no-target camera scenes.
- Audit old docs and scripts before any public release branch.

## 12. Rollback And Download

After this handoff checkpoint is pushed, rollback should use the tag:

```powershell
git fetch origin --tags
git checkout stable-demo-20260622-no-pose-dryrun
```

To return to the active branch after inspection:

```powershell
git checkout feature/new-pose-reintegration
```

The GitHub archive URL will be:

```text
https://github.com/kangzhouyang/69-service-/archive/refs/tags/stable-demo-20260622-no-pose-dryrun.zip
```

## 13. Safety Notes For The Next Engineer

- Do not print or commit `MAIN_SYSTEM_ALERT_TOKEN`.
- Do not commit `.env`.
- Do not commit local RTSP passwords.
- Do not disable dry-run for casual frontend testing.
- Do not start the old `69-service`.
- Do not enable pose in the stable demo baseline.
- If a real bridge POST is needed, treat it as an explicitly approved one-shot test, then immediately restore dry-run.

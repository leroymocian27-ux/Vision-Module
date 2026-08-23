# Current System Information Package

Generated: 2026-07-08
Workspace: `D:\camera`

This document fills the requested "minimum information package" for current system diagnosis, model tuning, performance review, and main-system integration.

Secrets are intentionally masked. Do not paste the raw `.env` publicly because it contains RTSP and alert credentials.

## 1. Code Version

| Item | Value |
|---|---|
| Code root | `D:\camera` |
| Git repository | Not available in this folder |
| Current branch | Unknown, `D:\camera` has no `.git` |
| Current commit | Unknown, `D:\camera` has no `.git` |
| Uncommitted changes | Unknown, cannot use `git status` |

Relevant source directories exist locally:

```text
app/
models/
scripts/
tests/
docs/
frontend_demo/
identity_service/
```

Important runtime modules:

```text
app/main.py
app/core/config.py
app/services/detection_service.py
app/services/result_publisher_service.py
app/services/fall_event_reporter_service.py
app/services/tracking_worker_service.py
app/services/pose_worker_service.py
app/temporal/
app/fall/
```

## 2. Current Runtime Configuration

Source file: `.env`

Sanitized copy generated at:

```text
artifacts/current_system_info_20260708/env.sanitized
```

Current key configuration:

| Key | Current value |
|---|---|
| `DEFAULT_CAMERA_ID` | `camera_01` |
| `DEFAULT_RTSP_URL` | `rtsp://admin:***@192.168.8.252:10554/tcp/av0_0` |
| `MOCK_CAMERA_ENABLED` | `false` |
| `CAPTURE_BACKEND` | `opencv` |
| `STREAM_STALE_THRESHOLD_MS` | `3000` |
| `STREAM_STALE_RECONNECT_AFTER_MS` | `6000` |
| `DETECTION_ENABLED` | `true` |
| `YOLO_MODEL_PATH` | `yolov8n.pt` |
| `YOLO_CONFIDENCE` | `0.35` |
| `YOLO_IMGSZ` | `512` |
| `YOLO_DEVICE` | `cuda:0` |
| `DETECTION_INTERVAL_MS` | `200` |
| `FALL_DETECTOR_ENABLED` | `true` |
| `YOLO_FALL_MODEL_PATH` | `models/yolo_fall_hint_candidate_v3_c_temporal_friendly_20260705.pt` |
| `YOLO_FALL_CONFIDENCE` | `0.25` |
| `YOLO_FALL_IMGSZ` | `512` |
| `ENABLE_TRACKING` | `true` |
| `TRACKING_WORKER_FPS` | `12` |
| `ENABLE_POSE` | `true` |
| `POSE_PROVIDER` | `yolo11_legacy` |
| `POSE_WORKER_FPS` | `1` |
| `POSE_RESULT_TTL_MS` | `800` |
| `POSE_MAX_FRAME_AGE_MS` | `800` |
| `POSE_INFERENCE_LOCK_WAIT_MS` | `160` |
| `ENABLE_TEMPORAL` | `true` |
| `TEMPORAL_MODEL_PROVIDER` | `onnx_lstm` |
| `TEMPORAL_ONNX_MODEL_PATH` | `models/fall_lstm_v5.onnx` |
| `FEATURE_WINDOW_SIZE` | `32` |
| `TEMPORAL_MODEL_WINDOW_SIZE` | `32` |
| `TEMPORAL_MODEL_INPUT_DIM` | `15` |
| `FALL_CONFIRM_FRAMES` | `3` |
| `FALL_STILL_MS` | `900` |
| `COOLDOWN_SECONDS` | `10` |
| `MAIN_SYSTEM_ALERT_ENABLED` | `true` |
| `MAIN_SYSTEM_REPORT_DRY_RUN` | `false` |
| `MAIN_SYSTEM_BASE_URL` | `http://192.168.8.248:8000/api/v1` |
| `MAIN_SYSTEM_FALL_EVENT_PATH` | `/video-bridge/fall-events` |
| `VISION_SERVICE_PUBLIC_BASE_URL` | `http://192.168.8.249:8000` |

Missing from current `.env`, so defaults may apply:

```text
FALL_EVIDENCE_CONFIRM_THRESHOLD
ADL_SUPPRESSION_CONFIRM_MAX
ADL_SUPPRESSION_BLOCK_THRESHOLD
TRACK_QUALITY_MIN_CONFIRM
FALL_DETECTOR_INTERVAL_MS
```

## 3. Current Runtime Status

Generated API captures:

```text
artifacts/current_system_info_20260708/healthz.json
artifacts/current_system_info_20260708/status_camera_01.json
artifacts/current_system_info_20260708/stream_source_camera_01.json
artifacts/current_system_info_20260708/latest_result_camera_01.json
artifacts/current_system_info_20260708/connection_status.json
artifacts/current_system_info_20260708/alerting_status.json
```

Summary:

| Area | Status |
|---|---|
| FastAPI service | Running |
| Process | `python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| PID observed | `23032` |
| `/healthz` | `{"status":"ok"}` |
| Camera source | `rtsp://admin:***@192.168.8.252:10554/tcp/av0_0` |
| Camera connected | `false` |
| `stream_state` | `connecting` |
| `last_error` | `source open failed` |
| `frame_seq` | `0` |
| `capture_fps` | `0.0` |
| Detection | Enabled and model loaded, but no frames to process |
| Fall hint | Enabled, but no frames to process |
| Tracking | Tracker running, no tracked objects |
| Pose | Enabled, skips because tracking has no objects |
| Temporal | Enabled, model loaded |
| Latest result API | `VISION_RESULT_NOT_READY` because no camera frame/result exists |
| Main-system connection | Timeout |
| Alerting | Enabled, dry-run false, target configured |

Current blocker:

```text
RTSP capture is not producing frames.
All downstream AI stages are effectively idle because the frame buffer is empty.
```

## 4. Current Model Inventory

Generated inventory:

```text
artifacts/current_system_info_20260708/models_inventory.json
artifacts/current_system_info_20260708/runtime_assets_inventory.json
```

Core files now present as real model binaries, not 130-byte LFS pointers:

| File | Purpose | Size |
|---|---:|---:|
| `yolov8n.pt` | Person detector baseline | `6,549,796` B |
| `yolo11n-pose.pt` | YOLO11 pose baseline | `6,255,593` B |
| `models/yolo_fall_hint_candidate_v3_c_temporal_friendly_20260705.pt` | Current fall hint detector | `5,455,706` B |
| `models/yolo_fall_hint_v2_plus_b012_best.pt` | Stable fall hint candidate | `5,461,914` B |
| `models/fall_lstm_v5.onnx` | Temporal LSTM | `85,630` B |

Runtime loaded according to `/status`:

| Runtime slot | Loaded/configured model |
|---|---|
| Person detection | `yolov8n.pt` |
| Fall hint | `models/yolo_fall_hint_candidate_v3_c_temporal_friendly_20260705.pt` |
| Pose | `yolo11n-pose.pt` |
| Temporal | `models/fall_lstm_v5.onnx` |

Important nuance:

```text
Models appear restored, but no runtime inference can be meaningfully evaluated until RTSP frames arrive.
```

## 5. Dataset And Label Definitions

Available locally:

```text
tests/fixtures/*.mp4
evaluations/**
models/*metrics.json
models/*train_config.json
models/*threshold_calibration.json
```

Still not confirmed from current local evidence:

```text
Current train/validation/test split definitions
Whether datasets are isolated by camera/person
Exact current field camera inclusion in training data
Full ADL negative taxonomy used for training
Current false-positive/false-negative sample table
```

Minimum human-supplied samples still needed:

```text
10 false positive samples
10 false negative samples
5 normal samples
5 true fall samples
```

Recommended sample metadata:

```json
{
  "sample_id": "fp_001",
  "camera_id": "camera_01",
  "video_path": "...",
  "timestamp_start": "...",
  "timestamp_fall_or_action": "...",
  "expected": "normal / fall_confirmed / suppressed",
  "actual": "fallen_confirmed",
  "problem_type": "false_positive",
  "description": "...",
  "lighting": "day / night / backlight",
  "occlusion": "none / partial / severe",
  "people_count": 1
}
```

## 6. Error Samples And Logs

Earlier runtime problem:

```text
camera_01 could not open RTSP source before the 2026-07-08 RTSP fix.
```

Current post-fix runtime problem:

```text
RTSP frame input is restored.
Main-system connection still times out.
No person is currently visible in the frame, so tracking/pose/fusion still need a person-visible validation pass.
```

Recent log patterns:

```text
source open failed
capture_slow_read
GET /api/v1/alarms?active_only=true -> 404
GET /api/v1/care/community/dashboard -> 404
WebSocket /ws/alarms -> 403
```

Interpretation:

```text
The 404/403 entries are requests for main-system/frontend endpoints sent to the Vision Service.
They are likely integration/base-URL mistakes, not internal Vision Service crashes.
```

Still needed:

```text
Recent real false-positive/false-negative videos or snapshots
Fall event POST response logs after a confirmed event
Main-system backend logs for 192.168.8.248
```

## 7. Hardware And Runtime Environment

| Item | Value |
|---|---|
| OS | Microsoft Windows 11 Home Chinese, 64-bit |
| OS version | `10.0.26200` |
| Python | `3.11.15` |
| Python executable | `C:\Users\Test1\.conda\envs\health\python.exe` |
| CPU | 11th Gen Intel Core i7-11800H |
| CPU cores/threads | 8 cores / 16 logical processors |
| Memory | ~15.8 GiB total |
| GPU | NVIDIA GeForce RTX 3060 Laptop GPU |
| GPU VRAM | 6 GiB |
| NVIDIA driver | `546.30` |
| CUDA shown by nvidia-smi | `12.3` |
| Torch | `2.5.1+cu121` |
| Torch CUDA available | `true` |
| Torch CUDA build | `12.1` |
| ONNX Runtime | `1.24.3` |
| ONNX Runtime providers | `AzureExecutionProvider`, `CPUExecutionProvider` |
| Ultralytics | `8.4.45` |
| OpenCV | `4.13.0` |
| NumPy | `2.4.4` |
| Pydantic | `2.11.3` |

Dependency snapshot:

```text
artifacts/current_system_info_20260708/pip_freeze.txt
```

Performance caveat:

```text
PyTorch can use CUDA, but onnxruntime-gpu is not installed/available.
Temporal ONNX currently runs with CPUExecutionProvider.
```

## 8. Current Performance Metrics

Because RTSP capture currently fails, meaningful AI performance metrics are not available.

Current observed metrics:

| Metric | Current value |
|---|---:|
| Camera input FPS | `0.0` |
| Detection FPS | `0.0` |
| Fall hint FPS | `0.0` |
| Result publish FPS | `0.0` |
| Tracking worker FPS | ~`10.8`, but no objects |
| Pose FPS | `0.0` |
| Main-system POST latency | Not observed, no confirmed fall event |

Primary performance blocker:

```text
No input frames from RTSP, so downstream timings cannot be evaluated yet.
```

## 9. Expected Realtime Targets

Not confirmed by product/operations yet.

Recommended starting targets for acceptance:

| Target | Suggested value |
|---|---|
| Cameras | 1 route first |
| Capture resolution | 1280x720 or camera native, downscale for analysis if needed |
| Capture FPS | 10-15 FPS minimum stable |
| Analysis FPS | 5-10 FPS target |
| Fall alert latency | <= 3 seconds after confirmed fall posture/stillness |
| Reconnect after stale stream | within 6-10 seconds |
| Duplicate alert cooldown | 90 seconds currently configured |

Still needs human decision:

```text
Prefer recall over precision, or fewer interruptions over higher recall?
Acceptable false alarms per day per camera?
Whether to show suspected fall before confirmed fall?
Whether high/critical two-level popup is required?
```

## 10. Main-System Integration

Configured endpoint:

```text
http://192.168.8.248:8000/api/v1/video-bridge/fall-events
```

Current alerting config:

| Key | Value |
|---|---|
| Enabled | `true` |
| Dry-run | `false` |
| Token header | `X-Vision-Service-Token` |
| Token value | Masked |
| Vision public base URL | `http://192.168.8.249:8000` |

Current connection status:

```text
Vision service: online
Main system: timeout
```

Still needs confirmation from main-system side:

```text
Is 192.168.8.248:8000 currently running?
Is /api/v1/video-bridge/fall-events implemented?
Expected success HTTP code and response body
Expected failure HTTP codes
Whether X-Vision-Service-Token is required and value matches
Whether frontend uses active POST, polling, WebSocket, or SSE
Whether incident_id dedupe is implemented
Whether snapshot_url is displayed and reachable from main-system host
```

## 11. Camera And Site Information

Current configured camera:

```text
rtsp://admin:***@192.168.8.252:10554/tcp/av0_0
```

Previous scan found:

```text
192.168.8.252:10554 reachable
192.168.8.252:10080 reachable
```

Current runtime after `docs/rtsp_recovery_report_20260708.md`:

```text
RTSP source opens through OpenCV with FFmpeg TCP options.
stream_state=connected
connected=true
capture_fps ~= 14.9
frame_width=2304
frame_height=1296
```

Required OpenCV/FFmpeg option:

```env
OPENCV_FFMPEG_CAPTURE_OPTIONS=rtsp_transport;tcp|stimeout;5000000|max_delay;500000
```

Validated streams:

```text
/tcp/av0_0 over TCP = H.264 2304x1296 @ 15fps
/tcp/av0_1 over TCP = H.264 640x360 @ 15fps
UDP timed out in the current network/runtime environment.
```

Still needs field confirmation:

```text
Correct RTSP password
Whether stream path should be /tcp/av0_0 or /tcp/av0_1
Whether RTSP transport must be TCP or UDP
Camera codec/H.264/H.265 setting
Installation height
Installation angle
Field of view
Actual resolution/FPS
Day/night lighting
IR status
Reflective areas
Bed/chair/sofa/door/wall positions
Typical activity zone
Likely fall zones
```

## 12. Current Diagnosis

Current highest-priority blockers:

1. Main-system endpoint `192.168.8.248:8000` times out.
2. A person-visible AI chain validation pass is still needed.
3. Some frontend/main-system routes are being requested from Vision Service and returning 404/403.
4. `av0_0` is high resolution, so `av0_0` vs `av0_1` performance should be measured before finalizing runtime stream choice.

Current working parts:

```text
FastAPI service
Configuration loading
Model loading for person/fall hint/temporal
Tracking worker startup
Pose worker startup
Alerting service startup
Status/diagnostic endpoints
```

Recommended next actions:

1. Confirm main-system backend availability at `192.168.8.248:8000`.
2. Put a person in view and capture `status`, `latest_result`, and `latest-frame.jpg`.
3. Run a short `av0_0` performance baseline; if analysis FPS is too low, compare with `/tcp/av0_1`.
4. Fix frontend/main-system base URLs so `/api/v1/alarms`, `/api/v1/care/community/dashboard`, and `/ws/alarms` are not sent to Vision Service.
5. Collect real false-positive/false-negative samples for threshold and model tuning after the AI chain is validated.

# Vision Service Stable Demo Runbook - 2026-06-22

## Safe Default Configuration

Use this mode for local demos, frontend observation, replay validation, and handoff checks:

```text
MAIN_SYSTEM_REPORT_DRY_RUN=true
ENABLE_POSE=false
POSE_PROVIDER=disabled_placeholder
```

Expected runtime state:

- Bridge target: `http://192.168.8.254:8000/api/v1/video-bridge/fall-events`
- Alert token header name: `X-Vision-Service-Token`
- Reporter: enabled, dry-run
- Pose: disabled placeholder, no pose model loaded
- Temporal live runtime: disabled
- Old `69-service`: not started
- Real POST to main system: not sent

## Module Status

| Module | Current State | Participates In Live Demo | Notes |
| --- | --- | --- | --- |
| CaptureWorker replay | Enabled | Yes | Local video enters the live pipeline with FPS throttle. |
| DetectionService | Enabled | Yes | Produces person detections and fall candidates. |
| TrackingService | Enabled | Yes | Generates and maintains `track_id`. |
| ResultPublisherService | Enabled | Yes | Publishes `VisionResult` to WebSocket/latest result paths. |
| FallEventReporter | Enabled dry-run | Yes | Builds local fall events but skips real HTTP POST. |
| Bridge to main system | Verified | Default dry-run | One-shot real POST was verified earlier; current default is not to send. |
| Pose / skeleton | Disabled | No | `disabled_placeholder`; no pose weight is loaded. |
| Temporal / FallStateMachine | Code exists and tests pass | No | Temporal/FallStateMachine exists as a sequence enhancement module, but current live runtime is not enabled. |
| Old 69-service | Not started | No | Not part of current stable demo. |
| Frontend demo | Available | Yes | Demo page can observe stream state; WebSocket/polling can observe results. |

## Pre-Start Checklist

1. Confirm `.env` contains:

```text
MAIN_SYSTEM_REPORT_DRY_RUN=true
ENABLE_POSE=false
POSE_PROVIDER=disabled_placeholder
MAIN_SYSTEM_BASE_URL=http://192.168.8.254:8000/api/v1
MAIN_SYSTEM_FALL_EVENT_PATH=/video-bridge/fall-events
MAIN_SYSTEM_ALERT_TOKEN_HEADER=X-Vision-Service-Token
```

2. Confirm the current service is running:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/status
```

3. Confirm alerting status:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/alerting/status
```

4. Confirm the alerting response shows:

```text
dry_run=true
base_url=http://192.168.8.254:8000/api/v1
path=/video-bridge/fall-events
token_header=X-Vision-Service-Token
```

Do not print token values.

## Confirm Dry-Run

Use `/alerting/status` and verify:

```text
endpoint.dry_run=true
```

Use `/status` and verify the reporter status is safe:

```text
fall_event_reporter.last_post_status=dry_run_skipped
```

The safe log signal during replay is:

```text
fall_event_report_dry_run skipped_real_post
```

The unsafe log signal is:

```text
fall_event_reported status=200
```

If `dry_run=false` or a real POST success appears unexpectedly, stop the demo and do not continue.

## Confirm No-Pose

Use `/status` and verify:

```text
pose.pose_enabled=false
pose.pose_provider=disabled_placeholder
pose.pose_model_path=null
pose.pose_fps=0.0
```

`pose_worker_skipped ... disabled_placeholder` is normal. `yolo_pose_loaded` is not expected.

## Open Demo Page

Open:

```text
http://127.0.0.1:8000/demo
```

For a safe read-only check, do not click the manual alert button. The page should load and show stream status. In the current safe mode, no skeleton overlay is expected because pose is disabled.

## Run Local Fall Replay

Validated replay video:

```text
D:\Program\vision_service\logs\acceptance\cropped_recording_2026-06-20T07-32-20-181Z\run2\cropped_recording_run2.mp4
```

The service can accept the local file through `/stream/start`, and `CaptureWorker` throttles local video frames using the video FPS metadata.

Expected replay metadata:

```text
video_fps=2.0
replay_fps=2.0
frame_count=150
size=644x360
```

After replay validation, restore the normal camera source. Do not print camera passwords in reports or logs.

## Expected Replay Result

The validated replay produced:

```text
person_detected=YES
fall_candidate_detected=YES
track_id=1
fall_state=fallen_confirmed
event_type=fall_confirmed
risk_level=critical
incident_id=vision-fall-camera_01_track_1-20260622025323947918
```

Reporter behavior:

```text
last_post_status=dry_run_skipped
real_post_sent=NO
```

## WebSocket Verification

Connect to:

```text
ws://127.0.0.1:8000/ws/results?camera_id=camera_01
```

Expected during normal camera operation:

- WebSocket connects.
- Messages arrive for `camera_01`.
- `objects` contains current detections when a person is visible.

Expected during replay:

- `track_id=1`
- `fall_state=fallen_confirmed`
- `risk_level=critical`
- `incident_id` is non-empty.

## Polling Verification

Latest result:

```text
http://127.0.0.1:8000/integration/results/camera_01/latest
```

Fall alert polling:

```text
http://127.0.0.1:8000/integration/fall-alerts/camera_01/poll
```

Expected during replay:

- Latest result shows the confirmed fall event fields.
- Fall alert polling returns a local alert for the same incident.

When replay is not active, `fall-alerts` may return `no_alert`; that is normal.

## Forbidden Demo Operations

Do not:

- Set `MAIN_SYSTEM_REPORT_DRY_RUN=false`.
- Click or call `/alerting/simulation/send-once`.
- Send a real POST to the main system.
- Enable pose.
- Change `ENABLE_POSE=false`.
- Change `POSE_PROVIDER=disabled_placeholder`.
- Load `yolov8n-pose.pt`.
- Enable Temporal live runtime.
- Start old `69-service`.
- Print token values.
- Run `git add .`.
- Run `git commit -am "..."`.

## Troubleshooting

If `/status` is not reachable:

- Confirm the current `uvicorn app.main:app` process is running on port `8000`.
- Restart only the current Vision Service if needed.
- Do not start old `69-service`.

If replay consumes too quickly:

- Confirm `app/camera/capture_worker.py` includes the local file FPS throttle.
- Confirm the input video reports valid FPS through OpenCV.

If no fall incident appears during replay:

- Check WebSocket latest result and polling result first.
- Check logs for `fall_candidate_promoted`.
- Confirm the target replay file is the validated mp4 listed above.
- Do not change fall logic, risk logic, incident generation, snapshot logic, pose, or Temporal as part of demo troubleshooting.

If a real POST is observed:

- Stop the demo immediately.
- Restore `MAIN_SYSTEM_REPORT_DRY_RUN=true`.
- Restart only the current Vision Service.
- Recheck `/alerting/status`.

## Demo Talking Points

```text
当前演示版采用 no-pose 安全模式，通过人体检测、跌倒候选检测、目标跟踪、结果融合和事件上报模块完成跌倒事件生成。本地 replay 已验证可产生 fall_confirmed 事件，并通过 WebSocket / polling 被前端链路观察到。系统默认开启 dry-run，因此不会真实向主系统发送告警。Temporal/FallStateMachine 作为时序增强模块存在并通过测试，但当前 live runtime 未启用。
```

## Current Safe Handoff

Keep this state after demos:

```text
MAIN_SYSTEM_REPORT_DRY_RUN=true
ENABLE_POSE=false
POSE_PROVIDER=disabled_placeholder
```

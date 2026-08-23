# Fall Replay Dry-Run Final Handoff - 2026-06-22

## Current Safe Configuration

- Runtime PID: 27804
- Bridge target: `http://192.168.8.254:8000/api/v1/video-bridge/fall-events`
- Alert token header name: `X-Vision-Service-Token`
- Local/default bridge mode: `MAIN_SYSTEM_REPORT_DRY_RUN=true`
- Pose runtime: `pose_enabled=false`, `pose_provider=disabled_placeholder`, `pose_model_path=null`, `pose_fps=0.0`
- Temporal live runtime: disabled
- Old `69-service`: not started
- Real POST after dry-run guard: not sent

Do not print or commit token values. Keep dry-run enabled for local/frontend validation unless a one-shot real bridge test is explicitly approved.

## Replay Video

- Video path: `D:\Program\vision_service\logs\acceptance\cropped_recording_2026-06-20T07-32-20-181Z\run2\cropped_recording_run2.mp4`
- OpenCV opened: yes
- Video FPS: 2.0
- Replay FPS: 2.0
- Frame count: 150
- Size: 644x360

## CaptureWorker FPS Throttle

`app/camera/capture_worker.py` now treats local file sources as real-time replay inputs. When OpenCV opens a local video file, `CaptureWorker` reads `CAP_PROP_FPS`, falls back to 10 FPS if metadata is invalid, and waits between frames before pushing the next frame into `FrameBuffer`.

This keeps local mp4 replay inside the existing live pipeline:

```text
local fall video
-> CaptureWorker local file source
-> FrameBuffer
-> detection_service
-> tracking
-> ResultPublisherService
-> WebSocket / latest polling / fall-alert polling
-> FallEventReporter dry-run guard
```

The change is scoped to local file sources. RTSP, HTTP, mock camera, detection logic, fall logic, Temporal, pose, snapshot, incident, risk, and reporter semantics were not changed by this replay throttle.

## Verified Fall Detection Chain

Observed validated chain:

```text
local fall video
-> CaptureWorker local file source
-> FPS throttle at 2.0 FPS
-> detection_service
-> person detected
-> fall candidate detected
-> tracking track_id=1
-> fallen_candidate
-> fallen_confirmed
-> fall_confirmed event
-> risk_level=critical
-> incident_id generated
-> WebSocket observed
-> latest polling observed
-> fall-alert polling observed
-> reporter dry-run skipped_real_post
-> no real POST
```

Validated event:

- Incident ID: `vision-fall-camera_01_track_1-20260622025323947918`
- Event type: `fall_confirmed`
- Risk level: `critical`
- Max observed fall probability: `0.6754`
- Track ID: `1`
- States observed: `fallen_candidate`, `fallen_confirmed`

## WebSocket Observation

The replay run connected to:

```text
ws://127.0.0.1:8000/ws/results?camera_id=camera_01
```

WebSocket observed the live pipeline result with:

- `track_id=1`
- `fall_state=fallen_confirmed`
- `risk_level=critical`
- `incident_id=vision-fall-camera_01_track_1-20260622025323947918`

## Polling Observation

The replay run observed the same confirmed fall through:

```text
http://127.0.0.1:8000/integration/results/camera_01/latest
http://127.0.0.1:8000/integration/fall-alerts/camera_01/poll
```

Polling returned a local alert for the same incident ID with `event_type=fall_confirmed` and `risk_level=critical`.

## Dry-Run Reporter Result

The reporter stayed in dry-run mode and did not execute a real POST to the main system.

Observed safe log signal:

```text
fall_event_report_dry_run skipped_real_post target=http://192.168.8.254:8000/api/v1/video-bridge/fall-events event_type=fall_confirmed track_id=1 incident_id=vision-fall-camera_01_track_1-20260622025323947918
```

Safety checks:

- `fall_event_reported status=200`: not observed after guard
- `yolo_pose_loaded`: not observed
- old `69-service`: not observed
- token value: not printed

## Test Results

Final requested test sets:

```text
python -m pytest tests/test_capture_worker_replay.py -q
2 passed

python -m pytest tests/test_alerting_manual_send.py tests/test_fall_event_reporter_service.py tests/test_result_publisher_service.py tests/test_fall_alert_polling_api.py tests/test_end_to_end_pipeline.py -q
43 passed, 4 warnings

python -m pytest tests -q -k "fall or temporal or state_machine or result_publisher or stream or camera"
46 passed, 30 deselected, 4 warnings
```

## Demo Script

Current demo wording:

```text
当前演示版在 no-pose 模式下，通过人体检测、跌倒候选检测、目标跟踪、结果融合和事件上报模块完成跌倒事件生成；本地 replay 已验证可产生 fall_confirmed 事件，并通过 WebSocket / polling 被前端链路观察到。系统默认开启 dry-run，因此不会真实向主系统发送告警。Temporal/FallStateMachine 作为时序增强模块存在并通过测试，但当前 live runtime 未启用。
```

Recommended safe demo mode:

```text
MAIN_SYSTEM_REPORT_DRY_RUN=true
ENABLE_POSE=false
POSE_PROVIDER=disabled_placeholder
```

Use local-file replay with FPS throttle for safe fall incident demos. Do not call `/alerting/simulation/send-once` for this replay validation path.

## Caveats

- Temporal live runtime is not enabled in the current safe demo mode.
- Pose is not enabled, and no pose weight such as `yolov8n-pose.pt` is loaded.
- This replay validation proves the current no-pose detector/tracking/publisher/reporter-dry-run path can generate and expose a confirmed fall incident.
- Earlier project phases left unrelated worktree changes across docs, pose, detection, frontend, scripts, and tests. Before any commit, review and stage this stage's intended files separately:
  - `app/camera/capture_worker.py`
  - `tests/test_capture_worker_replay.py`
  - `docs/fall_replay_dryrun_final_handoff_20260622.md`

## Rollback / Safety Note

To return to the pre-replay behavior for local video files, remove the local-file FPS throttle from `CaptureWorker`. Keep the reporter dry-run guard and no-pose settings unchanged unless a separate approved stage explicitly changes them.

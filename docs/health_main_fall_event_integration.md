# Health Main Fall Event Integration

## Architecture

`vision_service` is the only service that runs YOLO, YOLOPose, LSTM temporal inference, and local video debugging. `health-main` receives final fall alerts and broadcasts them to the community dashboard and family mobile app.

Runtime flow:

```text
Camera
-> vision_service capture + fall detection
-> confirmed fall saves one JPEG snapshot
-> vision_service POSTs alert JSON to health-main
-> health-main creates a fall alarm
-> community dashboard shows a red alert with level and snapshot
-> family app receives the same alert and can view the camera stream
```

`vision_service` does not push continuous video to `health-main`. It only sends alert data and a snapshot URL for confirmed falls.

## Local Single-PC Test

Use different ports:

```text
vision_service: http://127.0.0.1:8000
health-main backend: http://127.0.0.1:8090
```

Recommended `vision_service` settings:

```text
ENABLE_TEMPORAL=true
TEMPORAL_MODEL_PROVIDER=shadow
TEMPORAL_ONNX_MODEL_PATH=models/fall_lstm_v3.onnx
TEMPORAL_FEATURE_SCHEMA_PATH=models/fall_lstm_v3_features.json
MAIN_SYSTEM_ALERT_ENABLED=true
MAIN_SYSTEM_BASE_URL=http://127.0.0.1:8090/api/v1
MAIN_SYSTEM_FALL_EVENT_PATH=/video-bridge/fall-events
VISION_SERVICE_PUBLIC_BASE_URL=http://127.0.0.1:8000
FALL_EVENT_SNAPSHOT_DIR=logs/fall_events/snapshots
```

Start the real camera stream with:

```powershell
C:\Users\YANG\.conda\envs\torchgpu\python.exe scripts\start_current_camera.py --rtsp-url "rtsp://admin:***@192.168.8.254:10554/tcp/av0_1" --api-port 8000 --capture-backend subprocess_opencv --temporal-provider shadow --no-wait
```

## Two-PC LAN Deployment

On the fall-detection PC:

```text
VISION_SERVICE_PUBLIC_BASE_URL=http://<fall-detection-pc-ip>:8000
MAIN_SYSTEM_BASE_URL=http://<health-main-pc-ip>:<backend-port>/api/v1
MAIN_SYSTEM_ALERT_ENABLED=true
```

The project root `.env` is auto-loaded by `vision_service`, so these values can
be stored directly in `D:\Program\vision_service\.env`.

Open the firewall for the `vision_service` HTTP port so `health-main`, the community dashboard, and family app can load the snapshot URL.

## Smoke Test

After `health-main` backend is running, send a synthetic fall event:

```powershell
python scripts\post_test_fall_event.py --main-system-base-url http://127.0.0.1:8090/api/v1
```

Expected:

```text
POST returns an alarm_id
community dashboard shows a red fall alert
family app receives the same alert
snapshot_url is displayed when provided
```

For a stronger acceptance check that also creates a smoke snapshot, verifies the snapshot URL, posts the fall event, and confirms the resulting alarm is visible:

```powershell
python scripts\health_main_integration_acceptance.py `
  --main-system-origin http://127.0.0.1:8090 `
  --main-system-base-url http://127.0.0.1:8090/api/v1 `
  --vision-public-base-url http://127.0.0.1:8000
```

If `vision_service` is not currently running, add:

```powershell
--skip-snapshot-reachability
```

The final JSON should include:

```text
ok=true
alarm_id=<created alarm id>
checks.alarm_visible.ok=true
```

## End-to-End Acceptance

1. Camera is stable: `connected=true`, `frame_seq` grows, `capture_fps>=8`.
2. Detection is running: `Persons>0`, `detection_fps>2`.
3. Temporal is enabled: `TEMPORAL_MODEL_PROVIDER=shadow`.
4. Confirmed fall creates a JPEG in `logs/fall_events/snapshots`.
5. `vision_service` POSTs `/api/v1/video-bridge/fall-events`.
6. `health-main` creates a fall alarm and broadcasts it.
7. Community dashboard and family app show the alert level and snapshot.

Failure behavior:

```text
health-main offline -> vision_service logs the failure and keeps detecting
snapshot write failure -> alert can still be sent without a snapshot
duplicate confirmed frames -> cooldown prevents repeated alerts
model fallback -> final fall_decision still controls event reporting
```

# Camera Stability Acceptance Plan

## Current Problem

The real camera pipeline is not producing stable frames. The service and frontend are alive, but the camera source is still failing before detection can run.

Current observed real-camera status:

```text
source = rtsp://admin:***@192.186.8.254:554/tcp/av0_1
connected = false
stream_state = connecting
frame_seq = 0
capture_fps = 0.0
last_error = stream closed
```

This means detection, tracking, pose, behavior, and temporal fall detection cannot be judged yet. They have no real frames to process.

The mock reference service on port 8001 has already shown that the software pipeline can run when frames are available.

## Execution Order

1. Probe the exact RTSP source until a URL yields at least one decoded video frame:

```powershell
C:\Users\YANG\.conda\envs\torchgpu\python.exe scripts\probe_rtsp_sources.py `
  --host 192.186.8.254 `
  --username admin `
  --password admin `
  --port 554
```

If the camera vendor provides a full RTSP URL, test it directly:

```powershell
C:\Users\YANG\.conda\envs\torchgpu\python.exe scripts\probe_rtsp_sources.py `
  --urls "rtsp://USER:***@CAMERA_IP:PORT/PATH"
```

2. Start the service with the stable camera-debug profile:

```powershell
C:\Users\YANG\.conda\envs\torchgpu\python.exe scripts\start_current_camera.py `
  --rtsp-url "rtsp://USER:***@CAMERA_IP:PORT/PATH" `
  --api-port 8000 `
  --capture-backend subprocess_opencv `
  --temporal-provider shadow `
  --no-wait
```

Keep pose disabled until capture and detection are stable. After that, restart with:

```powershell
--enable-pose
```

3. Run the camera input gate:

```powershell
C:\Users\YANG\.conda\envs\torchgpu\python.exe scripts\camera_acceptance_gate.py `
  --base-url http://127.0.0.1:8000 `
  --duration-sec 600 `
  --interval-sec 2
```

Short smoke run:

```powershell
C:\Users\YANG\.conda\envs\torchgpu\python.exe scripts\camera_acceptance_gate.py `
  --base-url http://127.0.0.1:8000 `
  --duration-sec 20 `
  --interval-sec 2
```

4. Only after the camera gate passes, validate detection:

```powershell
C:\Users\YANG\.conda\envs\torchgpu\python.exe scripts\camera_acceptance_gate.py `
  --base-url http://127.0.0.1:8000 `
  --duration-sec 120 `
  --interval-sec 2 `
  --require-detection `
  --require-person
```

5. Only after detection/tracking pass, enable pose and validate pose/temporal:

```powershell
C:\Users\YANG\.conda\envs\torchgpu\python.exe scripts\camera_acceptance_gate.py `
  --base-url http://127.0.0.1:8000 `
  --duration-sec 120 `
  --interval-sec 2 `
  --require-detection `
  --require-person `
  --require-pose `
  --require-temporal-track
```

## Acceptance Gates

Camera input is accepted only when:

```text
connected = true
stream_state = connected
frame_seq grows
frame_width/frame_height are not empty
capture_fps >= 8
frame_age_ms < 1000
last_error = null
reconnect_count does not increase during the gate window
```

Detection is accepted only after camera input passes and:

```text
detection_fps >= 2
tracked_objects_count > 0 when a person is visible
```

Pose and temporal are accepted only after detection/tracking pass and:

```text
pose_fps > 0
temporal.active_tracks > 0
temporal debug payload includes model/shadow output when a tracked person is present
```

## Runtime Defaults

Stable debugging profile:

```text
CAPTURE_BACKEND=subprocess_opencv
ENABLE_POSE=false
ENABLE_TEMPORAL=true
TEMPORAL_MODEL_PROVIDER=shadow
TEMPORAL_ONNX_MODEL_PATH=models/fall_lstm_v3.onnx
TEMPORAL_FEATURE_SCHEMA_PATH=models/fall_lstm_v3_features.json
```

Do not switch the production default to `onnx_lstm`. Use `onnx_lstm` only for fixed-camera limited trials after camera and detection gates pass.

# Current PFV2 Status

> Authoritative current state: [docs/post_fall_v2_current_state.md](docs/post_fall_v2_current_state.md).
> The local safe-demo default is Binary-First post_fall_v2; target-camera calibration, acceptance, and RTSP validation remain blocked, so P3_ALLOWED=NO.
> The historical material below is retained for rollback context and is not the current PFV2 decision architecture.

# Vision Service

Standalone realtime vision service for the elderly-care project.

Current baseline:

- Phase 1: RTSP capture, latest-frame buffer, WebRTC video, WebSocket results, health status, Ultralytics YOLO person detect.
- Phase 2.1: ByteTrack-based tracking over existing YOLO detections.
- Phase 2.2: Identity enrollment API and local identity profile storage.
- Fall detector branch: dedicated YOLO fall model for `fall/fallen` labels, kept separate from person detect and pose.

## Debug Rule

Before any main-system linkage, fall-alert, `/api/v1/vision/*`, `/integration/results`, or popup debugging, confirm system identity by probing APIs instead of guessing from IPs.

- Main system: `GET http://<ip>:8000/healthz` returns `app = "AIoT Elder Care Monitoring System"`
- Vision Service: `GET http://<ip>:8000/status` and `GET http://<ip>:8000/integration/results/camera_01/latest` return Vision fields such as `camera_id`, `latest_result`, `objects`, `detector`, `source_fps`, `analysis_fps`, `temporal`, and `fall_event_reporter`

Full rule: [docs/codex_debug_rules.md](/D:/Program/vision_service/docs/codex_debug_rules.md)

The service must not duplicate RTSP pulls. Realtime processing follows:

```text
RTSP
-> CaptureWorker
-> FrameBuffer
-> YOLO person detect
-> ByteTrack tracking
-> WebRTC video + WebSocket results
```

Identity enrollment is a sidecar management capability. It does not participate in realtime tracking until a later phase.

## Run

Recommended local GPU environment:

```powershell
cd D:\vision_service
D:\Anaconda\python.exe -m pip install -r requirements.txt
D:\Anaconda\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The service now auto-loads `D:\Program\vision_service\.env` on startup if present.
For LAN alert delivery, set `MAIN_SYSTEM_ALERT_ENABLED=true`, replace
`MAIN_SYSTEM_BASE_URL` with the receiver server IP, and set
`VISION_SERVICE_PUBLIC_BASE_URL` to this machine's LAN address.
See [docs/lan_alert_setup.md](/abs/path-placeholder).

Open:

```text
http://127.0.0.1:8000/demo
```

The service starts a mock camera by default when `DEFAULT_RTSP_URL` is empty. To use a real source, call:

```powershell
$body = @{
  camera_id = "camera_01"
  rtsp_url = "rtsp://user:***@host/stream"
} | ConvertTo-Json

Invoke-RestMethod http://127.0.0.1:8000/stream/start `
  -Method POST `
  -ContentType "application/json" `
  -Body $body
```

## Key Endpoints

- `GET /healthz`
- `GET /status`
- `POST /stream/start`
- `POST /stream/stop`
- `POST /webrtc/offer`
- `WS /ws/results?camera_id=camera_01`
- `POST /identity/enroll`
- `GET /identity/list`
- `DELETE /identity/{person_id}`

## Config

Important phase flags:

```text
ENABLE_TRACKING=true
ENABLE_IDENTITY=false
ENABLE_TARGET_BINDING=false
FALL_DETECTOR_ENABLED=true
YOLO_FALL_MODEL_PATH=models/yolo_fall_hint_v2_plus_b012_best.pt
```

Pose config now supports two practical providers:

```text
POSE_PROVIDER=yolo
YOLO_POSE_MODEL_PATH=yolo26n-pose.pt
```

For controlled staging of the historical full-frame path without changing the
default runtime, enable:

```text
POSE_PROVIDER=yolo11_legacy
YOLO11_POSE_MODEL_PATH=D:\Program\health(5-12)\pose_detection_model_bundle\yolo11n-pose.pt
YOLO11_POSE_IMGSZ=640
YOLO11_POSE_CONF=0.12
YOLO11_POSE_HALF=true
YOLO11_POSE_SMOOTHING=true
YOLO11_POSE_MAX_JUMP_RATIO=0.18
```

or the stronger top-down RTMPose upgrade path:

```text
POSE_PROVIDER=rtmpose
RTMPOSE_CONFIG_PATH=models/rtmpose/rtmpose-l_8xb256-420e_coco-384x288.py
RTMPOSE_CHECKPOINT_PATH=models/rtmpose/rtmpose-l_simcc-coco_pt-aic-coco_420e-384x288-9ec0a4e5_20230127.pth
RTMPOSE_DEVICE=cuda:0
RTMPOSE_BBOX_THR=0.2
```

For this repo, the current most practical runtime upgrade path is the lighter
ONNX provider that reuses the existing tracked person boxes:

```text
POSE_PROVIDER=rtmpose_onnx
RTMPOSE_ONNX_MODEL_PATH=models/rtmpose/rtmpose-x-body7-384x288.onnx
RTMPOSE_ONNX_INPUT_WIDTH=288
RTMPOSE_ONNX_INPUT_HEIGHT=384
RTMPOSE_DEVICE=cuda:0
```

After project-specific adaptation training, the higher-quality runtime path is:

```text
POSE_PROVIDER=mmpose
RTMPOSE_CONFIG_PATH=models/rtmpose/rtmpose_l_pose_adaptation_384x288.py
RTMPOSE_CHECKPOINT_PATH=models/rtmpose/rtmpose-l-pose-adapted-best.pth
RTMPOSE_DEVICE=cuda:0
```

This path should be launched with the `torchgpu` Conda environment because it
contains the OpenMMLab training/inference stack required by `mmpose`.

`RTMPose` fits this service well because the pipeline already has tracked person
boxes and only needs a higher-quality single-person pose estimator on top of
those boxes. Compared with the current Ultralytics pose path, it is the
recommended upgrade candidate when you want better keypoint quality without
rewriting the rest of the temporal pipeline.

To use `RTMPose`, install the OpenMMLab runtime stack first:

```powershell
pip install openmim
mim install mmengine
mim install "mmcv>=2.0.0,<2.2.0"
mim install "mmdet>=3.0.0,<3.4.0"
pip install mmpose
```

If you prefer the lighter ONNX route, install only:

```powershell
py -3.10 -m pip install rtmlib onnxruntime
python -m pip install onnxruntime
```

Identity enrollment config:

```text
IDENTITY_STORE_DIR=data/identities
IDENTITY_MAX_IMAGES=5
INSIGHTFACE_MODEL_NAME=buffalo_l
INSIGHTFACE_CTX_ID=0
INSIGHTFACE_DET_SIZE=640
INSIGHTFACE_PROVIDERS=
```

Set `ENABLE_IDENTITY=true` before using `/identity/enroll`. If InsightFace fails to load, the service still starts. Only the identity API returns a clear error.

Install optional identity dependencies separately:

```powershell
pip install -r requirements-identity.txt
```

On Windows, `insightface` may try to build native extensions if a wheel is not available. If that happens, install Microsoft C++ Build Tools or use a Conda/package source that provides a compatible prebuilt package.

## RTSP Health

`connected=true` only means the capture backend believes the source is open. It does not guarantee that fresh frames are still arriving.

Use these fields together:

- `stream_state`: `disconnected`, `connecting`, `connected`, `stale`, or `reconnecting`.
- `frame_age_ms`: age of the latest frame in the shared `FrameBuffer`.
- `capture_fps`: recent capture FPS.
- `reconnect_count`: number of reconnect attempts.
- `last_frame_at`: UTC timestamp of the latest captured frame.

Default stale thresholds:

```text
STREAM_STALE_THRESHOLD_MS=3000
STREAM_STALE_RECONNECT_AFTER_MS=6000
```

If `stream_state=stale`, the RTSP TCP connection may still be alive, but the image is no longer updating. The frontend should show this as "画面停滞/正在恢复", not as a normal connection.

The current implementation uses OpenCV timeout properties plus a lightweight watchdog. If `cv2.VideoCapture.read()` blocks inside the native backend longer than expected, watchdog execution can be delayed. If this becomes frequent in deployment, the next engineering step is a subprocess or FFmpeg-based capture worker, not adding model logic.

## Tracking

Tracking consumes existing YOLO detections:

```text
FrameBuffer -> YOLO detections -> ByteTrack.update()
```

It does not call `model.track(rtsp_url)` and does not open RTSP.

WebSocket object example:

```json
{
  "track_id": 3,
  "label": "person",
  "bbox": [10, 20, 100, 220],
  "confidence": 0.92,
  "is_target": true,
  "person_id": null,
  "person_name": null,
  "identity_state": "target_locked"
}
```

Phase 2.1 target selection is temporary and tracking-only. It is not a real elderly identity binding.

## Identity Enrollment

Phase 2.2 supports local identity registration only. It does not bind identities to realtime tracks yet.

Enable identity:

```powershell
$env:ENABLE_IDENTITY="true"
D:\Anaconda\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Enroll with multipart files:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/identity/enroll" `
  -F "person_id=elder_001" `
  -F "person_name=张奶�? `
  -F "replace_existing=true" `
  -F "files=@D:\faces\elder_001_1.jpg" `
  -F "files=@D:\faces\elder_001_2.jpg"
```

Response:

```json
{
  "person_id": "elder_001",
  "person_name": "张奶�?,
  "faces_registered": 2,
  "status": "success"
}
```

List identities:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/identity/list |
  ConvertTo-Json -Depth 10
```

Delete identity:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/identity/elder_001 -Method DELETE
```

Storage layout:

```text
data/identities/
  elder_001/
    profile.json
    embeddings.npy
    faces/
      001.jpg
      002.jpg
```

`embeddings.npy` stores L2-normalized embeddings. `profile.json` records:

```json
{
  "person_id": "elder_001",
  "person_name": "张奶�?,
  "embedding_count": 2,
  "model_name": "buffalo_l",
  "created_at": "...",
  "updated_at": "..."
}
```

Safety boundaries:

- Do not log uploaded image bytes or base64.
- If no face is detected, `/identity/enroll` returns a clear `400` error.
- If InsightFace cannot load, `/identity/enroll` returns a clear `503` error.
- Identity failures do not affect RTSP, WebRTC, YOLO, or tracking.

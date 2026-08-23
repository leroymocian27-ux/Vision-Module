# S3 Camera Stream Current Flow

Date: 2026-07-20
Stage: `S3_CAMERA_AND_VIDEO_STREAM_RESILIENCE`

## Current Code Chain

```text
POST /stream/start
-> app.api.rest_api.start_stream
-> StreamService.start
-> StreamService._reset_camera_state
-> CameraSourceManager.start_source
-> FrameBuffer
-> CaptureWorker or SubprocessCaptureWorker
-> DetectionService reads FrameBuffer.latest()
-> Tracking/Pose/Temporal/Fusion/Publisher read RealtimeResultStore
-> GET /status through StatusService
-> GET /stream/latest-frame.jpg through FrameBuffer.latest()
```

## Source Components

- `CameraSourceManager`: owns active `CameraRuntime` objects by camera id.
- `CaptureWorker`: handles mock, local files, and OpenCV capture.
- `SubprocessCaptureWorker`: handles subprocess capture backends for non-mock sources.
- `FrameBuffer`: stores the latest non-consuming `FramePacket`.
- `StreamService`: starts/stops source, workers, and resets per-camera AI state on source switch.
- `StatusService`: converts worker status into `/status`.
- `rest_api.latest_stream_frame`: encodes the latest frame as JPEG.

## Camera State Source

Current worker states are produced inside `CaptureWorker.status()` and `SubprocessCaptureWorker.status()`. Existing values include:

```text
connecting
connected
stale
reconnecting
disconnected
```

These are useful but not yet mapped to the unified S3 public contract.

## Latest Frame Metadata Source

Current latest frame metadata comes from `FramePacket`:

```text
camera_id
seq
captured_at
width
height
age_ms
captured_at_iso
```

Missing before S3:

```text
source
source_generation
received_at
frame_status
is_stale
```

## No-Frame Handling

`/stream/latest-frame.jpg` returns 404 when no `FramePacket` exists. Detection worker waits with `stop_event.wait(0.03)` when there is no frame or no new frame.

## Stale Handling

Workers derive `stale` when `frame_age_ms > settings.stream_stale_threshold_ms`. `latest-frame` can still return the old frame but did not expose `X-Frame-Status` before S3.

## Reconnect Handling

OpenCV capture uses `ReconnectPolicy`. Current defaults are exponential backoff from `RECONNECT_INITIAL_DELAY_SEC` to `RECONNECT_MAX_DELAY_SEC`. Subprocess capture uses a fixed restart delay through `CAPTURE_PROCESS_RESTART_MS`.

## Source Switch Handling

`StreamService.start()` stops the existing source when the URL changes and then calls `_reset_camera_state()`. Existing reset coverage includes:

```text
tracking
identity binding
temporal service and temporal worker
fusion worker
FallFusionService camera state
fall hint worker
RealtimeResultStore
```

This already prevents old track, temporal, fused, fall hint, and latest result reuse across source switches.

## Known Risks

- Public camera state is not yet normalized to the S3 contract.
- Frame generation is not explicitly exposed.
- `latest-frame` lacks frame status and source generation headers.
- Mock source has no safe fault injection for pause/freeze/stop/resume.
- RTSP authentication and real reconnect acceptance remain `NOT_RUN`.

## Files Planned For This Round

```text
app/camera/frame_freshness.py
app/camera/frame_buffer.py
app/camera/capture_worker.py
app/camera/subprocess_capture_worker.py
app/camera/source_manager.py
app/schemas/status.py
app/services/status_service.py
app/api/rest_api.py
scripts/run_camera_stream_gate.py
tests/stabilization/
docs/stabilization/
```

## Files Explicitly Not Modified

```text
app/fall/fusion.py
app/services/fall_event_reporter_service.py
.env
```

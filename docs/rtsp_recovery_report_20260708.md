# RTSP Recovery Report

Generated: 2026-07-08
Workspace: `D:\camera`

## Summary

RTSP frame input has been restored.

Root cause found in this run:

```text
The camera stream itself was valid, but Vision Service started OpenCV capture without the FFmpeg RTSP options needed for this camera.
```

Fix applied:

```env
OPENCV_FFMPEG_CAPTURE_OPTIONS=rtsp_transport;tcp|stimeout;5000000|max_delay;500000
```

File changed:

```text
.env
```

Probe script added:

```text
tools/probe_rtsp_opencv.py
```

## Network Check

```text
192.168.8.252:10554  reachable = true
192.168.8.252:10080  reachable = true
```

## FFprobe Results

Artifacts:

```text
artifacts/rtsp_probe_20260708/ffprobe3_av0_0_tcp.log
artifacts/rtsp_probe_20260708/ffprobe3_av0_1_tcp.log
artifacts/rtsp_probe_20260708/ffprobe3_av0_0_udp.log
artifacts/rtsp_probe_20260708/ffprobe3_av0_1_udp.log
```

TCP works:

```text
av0_0 tcp:
  Video: H.264 High, 2304x1296, 15 fps
  Audio: pcm_alaw, 8000 Hz
  exit=0

av0_1 tcp:
  Video: H.264 High, 640x360, 15 fps
  Audio: pcm_alaw, 8000 Hz
  exit=0
```

UDP does not work in this environment:

```text
av0_0 udp: timeout after 12s
av0_1 udp: timeout after 12s
```

Conclusion:

```text
Use TCP transport.
Both /tcp/av0_0 and /tcp/av0_1 are valid.
```

## FFmpeg Screenshot Results

Artifacts:

```text
artifacts/rtsp_probe_20260708/rtsp_probe_av0_0_tcp.jpg
artifacts/rtsp_probe_20260708/rtsp_probe_av0_1_tcp.jpg
artifacts/rtsp_probe_20260708/ffmpeg_av0_0_tcp.log
artifacts/rtsp_probe_20260708/ffmpeg_av0_1_tcp.log
```

Results:

```text
av0_0 tcp screenshot saved, 82,084 bytes
av0_1 tcp screenshot saved, 14,037 bytes
```

## Minimal OpenCV Results

Command pattern:

```powershell
C:\Users\Test1\.conda\envs\health\python.exe tools\probe_rtsp_opencv.py "<rtsp-url>" "<output.jpg>"
```

Artifacts:

```text
artifacts/rtsp_probe_20260708/opencv_av0_0.log
artifacts/rtsp_probe_20260708/opencv_av0_1.log
artifacts/rtsp_probe_20260708/rtsp_opencv_probe_av0_0.jpg
artifacts/rtsp_probe_20260708/rtsp_opencv_probe_av0_1.jpg
```

Results:

```text
av0_0:
  OpenCV 4.13.0
  options = rtsp_transport;tcp|stimeout;5000000|max_delay;500000
  open_elapsed_ms = 2607.6
  first frame shape = (1296, 2304, 3)
  screenshot saved

av0_1:
  OpenCV 4.13.0
  options = rtsp_transport;tcp|stimeout;5000000|max_delay;500000
  open_elapsed_ms = 1992.74
  first frame shape = (360, 640, 3)
  screenshot saved
```

## Vision Service Validation

Service restarted after `.env` update.

Observed process:

```text
python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
PID: 42972
```

Current stream status:

```text
stream_state = connected
connected = true
frame_seq > 0
frame_width = 2304
frame_height = 1296
frame_age_ms ~= 15-47 ms
capture_fps ~= 14.9
```

Current AI/pipeline status:

```text
detection.enabled = true
detection.loaded = true
detection_fps ~= 4.19
fall_hint_fps ~= 4.19
tracking.tracker_running = true
result_publish_fps ~= 9.19
latest_result no longer returns VISION_RESULT_NOT_READY
```

Latest frame artifact:

```text
artifacts/rtsp_probe_20260708/vision_latest_frame.jpg
```

## Remaining Issues

Main system is still not reachable from Vision Service:

```text
main_system.base_url = http://192.168.8.248:8000
main_system.status = timeout
```

No person is currently detected in the latest frame:

```text
latest_raw_person_count = 0
tracked_objects_count = 0
pose skip reason = no_tracking
```

This may simply mean no person is visible in the current camera view. AI correctness should be tested after a person appears in-frame.

## Recommendation

Keep current camera transport as TCP.

For production runtime, consider switching analysis source to `/tcp/av0_1` if full-resolution `/tcp/av0_0` becomes too heavy:

```text
av0_0 = 2304x1296 @ 15fps
av0_1 = 640x360 @ 15fps
```

The current single-source service is using `/tcp/av0_0`, which now works but is heavier for AI inference.

## Persistent Configuration

This fix has been persisted in both runtime config and template config:

```text
.env
.env.example
```

Required setting:

```env
OPENCV_FFMPEG_CAPTURE_OPTIONS=rtsp_transport;tcp|stimeout;5000000|max_delay;500000
```

Use this as the first RTSP troubleshooting check if the service returns to:

```text
stream_state=connecting
last_error=source open failed
frame_seq=0
capture_fps=0.0
```

Do not switch to UDP for the current camera/network unless a new probe proves it works.

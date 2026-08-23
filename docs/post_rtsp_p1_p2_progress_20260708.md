# Post-RTSP P1/P2 Progress

Generated: 2026-07-08
Workspace: `D:\camera`

## Completed This Pass

1. Persisted the RTSP recovery setting in `.env.example`.
2. Updated current system documentation to reflect that RTSP is now restored.
3. Captured post-RTSP AI chain evidence under `artifacts/ai_chain_probe_20260708/`.
4. Checked main-system network status.
5. Ran a 3-minute `av0_0` performance sample.

## RTSP Fix Solidified

Persisted required option:

```env
OPENCV_FFMPEG_CAPTURE_OPTIONS=rtsp_transport;tcp|stimeout;5000000|max_delay;500000
```

Updated files:

```text
.env.example
docs/current_system_info_package_20260708.md
docs/rtsp_recovery_report_20260708.md
```

Current camera stream remains:

```text
rtsp://admin:***@192.168.8.252:10554/tcp/av0_0
```

## P1 Main-System Connectivity

Network probe artifact:

```text
artifacts/ai_chain_probe_20260708/main_system_network_probe.json
```

Observed result:

```text
host = 192.168.8.248
port = 8000
tcp_test_succeeded = false
ping_succeeded = false
```

Vision integration status artifact:

```text
artifacts/ai_chain_probe_20260708/connection_status_after_rtsp_fix.json
```

Observed result:

```text
vision_service.status = online
main_system.status = timeout
```

Conclusion:

```text
The main-system issue is still outside Vision Service. The host/port is not reachable from this machine.
```

Do not treat failed popup delivery as an AI failure until `192.168.8.248:8000` is reachable and the `fall-events` endpoint accepts POST requests.

## P2 AI Chain Evidence

Artifacts:

```text
artifacts/ai_chain_probe_20260708/status_person_visible.json
artifacts/ai_chain_probe_20260708/latest_person_visible.json
artifacts/ai_chain_probe_20260708/latest_person_visible.jpg
```

The person-visible snapshot showed:

```text
latest_raw_person_count = 1
tracked_objects_count = 1
objects count = 1
object label = person
object confidence = 0.9507
track_id = 40
pose.pose_quality_level = valid
pose.skeleton_confidence = 0.569
temporal.window_size = 11
temporal.window_ready = false
fall_state = normal
fall_detected = false
alarm_preview.confirmed = false
```

Interpretation:

```text
Person detection, tracking, pose attachment, temporal feature generation, and fusion fields are all present in at least one person-visible snapshot.
The temporal window was still warming up in that snapshot, so a longer person-visible run is still needed before judging temporal stability.
```

## P3 av0_0 3-Minute Performance Sample

Artifacts:

```text
artifacts/ai_chain_probe_20260708/perf_av0_0_3min_samples.json
artifacts/ai_chain_probe_20260708/perf_av0_0_3min_samples.csv
artifacts/ai_chain_probe_20260708/gpu_av0_0_3min_samples.json
```

Sampling note:

```text
The 3-minute sample was mostly/no-person, so it is valid for capture and detector loop stability,
but not valid for person tracking or pose stability.
```

Observed averages:

| Metric | Average | Min | Max |
|---|---:|---:|---:|
| capture_fps | 14.946 | 14.88 | 15.02 |
| detection_fps | 4.058 | 4.00 | 4.11 |
| fall_hint_fps | 4.058 | 4.00 | 4.11 |
| person inference ms | 19.099 | 10.49 | 58.82 |
| fall hint inference ms | 28.682 | 11.76 | 170.66 |
| tracking worker fps | 10.739 | 10.70 | 10.79 |
| pose_fps | 0.080 | 0.08 | 0.08 |
| result_publish_fps | 9.203 | 9.16 | 9.24 |
| frame_age_ms | 35.556 | 0 | 78 |

GPU during the final samples:

```text
GPU utilization varied around 15-55%.
GPU memory used was around 2473-2479 MiB / 6144 MiB.
GPU temperature was around 47 C.
```

Interpretation:

```text
av0_0 capture is stable at ~15 FPS.
The current combined person/fall-hint detection loop is ~4 FPS on 2304x1296 input.
This is below the suggested 5-10 FPS analysis target, so av0_1 A/B testing remains recommended.
```

## Remaining Work

P1:

```text
Bring main system online at 192.168.8.248:8000.
Verify /healthz or /api/v1/healthz.
Verify POST /api/v1/video-bridge/fall-events returns HTTP < 400.
Fix frontend/main-system base URL so /api/v1/alarms, /api/v1/care/community/dashboard, and /ws/alarms are not sent to Vision Service.
```

P2:

```text
Run a 30-60 second person-standing/person-walking capture while a person stays in view.
Confirm latest_raw_person_count >= 1, tracked_objects_count >= 1, stable track_id, pose valid, temporal window_ready=true, fall_detected=false.
```

P3:

```text
Run the same performance sample on /tcp/av0_1.
Compare detection_fps, fall_hint_fps, pose_fps, frame_age_ms, and detection quality.
```

P4:

```text
After P2/P3, split FallHintWorker if the combined detection loop remains the bottleneck.
```


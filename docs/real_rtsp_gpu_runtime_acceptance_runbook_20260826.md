# Real RTSP GPU Runtime Acceptance Runbook - 2026-08-26

This runbook is the required real-camera acceptance layer for the GPU runtime optimization.
Dummy ONNX inference and mock video benchmarks prove the local GPU path and code mechanics, but they do not prove real RTSP latency, browser smoothness, physical fall scenes, Qwen review, or main-system delivery.

## Scope

Use this document only after an authorized reachable RTSP source is available.

The acceptance target is:

- video connects first with no model auto-start;
- binary classification is manually enabled after video is visible;
- EfficientNet-B0 stays on `CUDAExecutionProvider`;
- binary sampling remains about `3 FPS`;
- video display remains about `12-15 FPS` without growing delay;
- AI uses recent frames, not historical backlog;
- Qwen and main-system contracts remain compatible;
- legacy YOLO, pose, tracking, and red/green realtime overlay remain disabled for this profile.

Do not lower `POST_FALL_V2_SAMPLE_FPS` below `3` to pass this runbook.

## Preconditions

Record these before testing:

| Item | Expected | Actual |
| --- | --- | --- |
| Project root | `E:\国赛\camera-service` | |
| GPU Python | `E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe` | |
| Rollback Python | `E:\国赛\camera-service\.venv\Scripts\python.exe` | |
| RTSP source authorized | yes | |
| Main system endpoint available if delivery is tested | yes/no | |
| Qwen/Ollama endpoint available if Qwen is tested | yes/no | |
| Browser used | Chrome/Edge/etc. | |

Provider precheck:

```powershell
cd E:\国赛\camera-service
E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe -c "import onnxruntime as ort; print(ort.__version__); print(ort.get_available_providers())"
nvidia-smi
```

Pass condition:

- provider list includes `CUDAExecutionProvider`;
- GPU is visible in `nvidia-smi`;
- there is no unrelated long-running Python GPU process that could distort benchmark results.

## Step 1 - Start Clean

Close any old service on port `8000`, or choose a temporary benchmark port.

Start the visual service for manual browser testing:

```powershell
cd E:\国赛\camera-service
.\scripts\start_visual_gpu.ps1
```

Expected startup state:

- service is healthy;
- binary model is not enabled;
- Qwen is not enabled;
- no binary worker is running before a stream is connected and the binary button is pressed.

Record status before connecting video:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/runtime-control/status?camera_id=camera_01" |
  ConvertTo-Json -Depth 10
```

Also save a structured runtime diagnosis:

```powershell
.\scripts\diagnose_gpu_runtime.ps1 `
  -JsonOut "artifacts/environment_audit/real_rtsp_before_stream_diagnosis.json"
```

Pass condition:

- `binary_enabled=false`;
- `qwen_enabled=false`;
- `runtime.running=false`;
- `runtime.binary_model_loaded=false` before manual enable.

## Step 2 - Run 300-Second Machine Benchmark

Use the same real RTSP source for all scenarios:

```powershell
cd E:\国赛\camera-service
.\scripts\benchmark_real_rtsp_comparison.ps1 `
  -SourceUrl "rtsp://<user>:<password>@<host>:<port>/<path>" `
  -CameraId "camera_01" `
  -DurationSeconds 300
```

This produces:

- GPU video-only summary;
- `.venv` CPU binary baseline summary;
- Conda GPU binary summary;
- one combined `.comparison.json`;
- one redacted `.comparison.md`.

After the run, check the comparison:

```powershell
.\scripts\check_runtime_acceptance.ps1 `
  -ComparisonPath "artifacts/environment_audit/<label>.comparison.json"
```

Machine pass conditions:

| Check | Pass condition |
| --- | --- |
| GPU binary scenario | completed |
| Manual model control | `after_binary_enabled=true` and `after_binary_loaded=true` only after stream/manual enable |
| Provider | `binary_provider=CUDAExecutionProvider` and `binary_provider_degraded=false` |
| Binary sample rate | `2.4 <= binary_fps <= 3.4` |
| Latest-frame queue | `queue_depth_max <= 1` |
| Camera frame age | average `<= 300 ms` and trend `<= 5 ms/s` when enough samples exist |
| Binary frame age | trend `<= 5 ms/s` when enough samples exist |
| CPU pressure | Conda GPU binary CPU is at least `50%` lower than `.venv` CPU binary |
| Video-only baseline | summary exists for the same RTSP source |

If `acceptance_status=UNKNOWN`, inspect the unknown checks. It is acceptable only when a required external scenario was intentionally skipped or the run was too short for trend evidence. For a full 300-second real RTSP run, unresolved `UNKNOWN` should be treated as incomplete acceptance.

## Step 3 - Browser Visual Smoothness

Open the frontend and connect the same RTSP source from the page.

Test sequence:

| Action | Expected observation | Actual |
| --- | --- | --- |
| Connect RTSP, models off | realtime video visible; no detection overlay boxes | |
| Watch 60 seconds, models off | no gradually increasing delay | |
| Enable binary only | video remains continuous; no red/green box overlay | |
| Watch 120 seconds, binary on | delay does not grow; motion stays readable enough for fall posture | |
| Disable binary | video remains connected; binary status turns off | |
| Enable binary again | provider returns CUDA; no runaway delay | |
| Enable Qwen after binary | Qwen button works only after binary is running | |

Browser pass conditions:

- visual display feels continuous at roughly `12-15 FPS`;
- no increasing lag is visible over several minutes;
- frontend diagnostics show `Provider=CUDAExecutionProvider`, `Sample FPS=3`, low queue depth, and bounded AI frame age;
- JPG fallback polling does not continue when WebRTC video is healthy;
- no realtime fall status boxes are drawn over the video.

If the browser becomes slow after enabling binary classification, save a diagnosis immediately:

```powershell
.\scripts\diagnose_gpu_runtime.ps1 `
  -JsonOut "artifacts/environment_audit/real_rtsp_binary_on_lag_diagnosis.json" `
  -FailOnCpuBinaryProvider
```

If this exits with code `2`, the service is running binary classification on `CPUExecutionProvider`, which is a direct explanation for the severe lag class observed before the GPU optimization.

## Step 4 - Physical Scene Regression

Run each scene with binary enabled. Enable Qwen for the fall scenes when the Qwen endpoint is available.

| Scene | Duration | Expected result | Actual |
| --- | ---: | --- | --- |
| Empty scene | 60s | no FallEvent | |
| Standing still | 60s | no FallEvent | |
| Normal walking/movement | 120s | no FallEvent; no sustained frame-age growth | |
| Intentional low posture / lying down | 120s | should not be treated as confirmed real fall by Qwen unless scene truly matches fall criteria | |
| Real fall simulation | 3 attempts | binary event is created; Qwen confirm/deny is recorded; event IDs align | |

Pass conditions:

- binary classification still runs at about `3 FPS`;
- normal/empty scenes do not create repeated false fall events;
- real fall simulation creates a binary event;
- Qwen review, when enabled and reachable, creates a corresponding confirm or deny artifact;
- a binary fall event ID can be found in the corresponding Qwen confirm/deny folder when Qwen completes.

## Step 5 - Test Event Archive Check

When timed testing is used, inspect:

| Folder | Expected content |
| --- | --- |
| `E:\国赛\event\binary-classification\full` | every binary event that would be sent to Qwen |
| `E:\国赛\event\binary-classification\other` | binary non-fall frame records captured during the timed test |
| `E:\国赛\event\qwen\confirm` | Qwen-confirmed real fall events with keyframes and JSON |
| `E:\国赛\event\qwen\deny` | Qwen-denied binary fall events with keyframes and JSON |

Event consistency rule:

```text
binary full event count = qwen confirm count + qwen deny count
```

This equality is required only for binary fall events that were submitted to Qwen and reached a terminal Qwen result during the test window. If Qwen is disabled, unreachable, timed out, or the test stops before review completion, record the exception explicitly.

For every Qwen confirm/deny event directory, verify:

- a matching binary event directory exists under `binary-classification\full`;
- the incident/event ID or folder name matches;
- keyframe images are present;
- Qwen JSON is present;
- `fall_verdict` and `archive_eligible` semantics remain unchanged.

## Step 6 - Main-System Delivery Check

Run this only when the main-system endpoint is authorized and available.

For a Qwen-approved real fall event:

| Check | Expected | Actual |
| --- | --- | --- |
| FallEvent external structure | unchanged | |
| URL/IP discovery behavior | unchanged | |
| port pairing behavior | unchanged | |
| alert JSON fields | unchanged | |
| delivery timing | same business semantics as before optimization | |
| delivery result | accepted by main system or expected dry-run response | |

Pass condition:

- the main system does not need to know whether the vision service is using `.venv` or Conda;
- no URL, protocol, JSON field, event ID, `fall_verdict`, or `archive_eligible` contract change is required because of the GPU optimization.

## Step 7 - Disconnect / Reconnect Regression

With the browser open and binary enabled:

| Action | Expected observation | Actual |
| --- | --- | --- |
| Disconnect RTSP source | stream reports disconnected/stale; service remains alive | |
| Reconnect same RTSP source | video returns without restarting the whole service | |
| Re-enable binary if needed | worker starts once; provider remains CUDA | |
| Check status | no duplicate worker/thread growth is visible | |

Useful checks:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/status" | ConvertTo-Json -Depth 10
Invoke-RestMethod "http://127.0.0.1:8000/runtime-control/status?camera_id=camera_01" |
  ConvertTo-Json -Depth 10
```

Pass condition:

- no sustained stale frame age after reconnect;
- no duplicate binary workers for the same camera;
- no growing VLM queue after Qwen is disabled or completed.

## Result Template

Fill this in after the real run:

| Item | Result |
| --- | --- |
| Comparison JSON | |
| Comparison Markdown | |
| `check_runtime_acceptance.ps1` exit code | |
| GPU provider after binary enable | |
| GPU provider degraded | |
| Binary FPS | |
| CPU drop from `.venv` CPU baseline | |
| Camera frame age avg/max/trend | |
| Binary frame age avg/max/trend | |
| Browser visual result | |
| Scene regression result | |
| Qwen confirm/deny event consistency | |
| Main-system delivery result | |
| Disconnect/reconnect result | |
| Final acceptance | PASS / FAIL / INCOMPLETE |

## Failure Triage

Use this order when a real RTSP run fails:

1. If `binary_provider` is not `CUDAExecutionProvider`, fix the runtime environment or DLL/provider loading first.
2. If provider is CUDA but CPU remains high, inspect capture/JPEG IPC and browser fallback duplication.
3. If `camera_frame_age_trend_ms_per_s` grows, inspect RTSP capture buffering and any queue that accumulates frames.
4. If `binary_frame_age_trend_ms_per_s` grows but camera age is stable, inspect binary queue and inference latency.
5. If browser is choppy but machine metrics pass, inspect WebRTC playback, JPG fallback polling, and frontend rendering.
6. If Qwen event counts do not match binary full events, inspect Qwen queue timeouts, event terminal status, and archive completion timing.

Do not treat a passing mock run as real acceptance. Do not treat a real run as passing until the machine benchmark, browser observation, scene regression, and relevant Qwen/main-system checks have matching evidence.

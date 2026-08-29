# GPU Runtime Optimization Report - 2026-08-26

## Current Result

Post-Fall V2 binary classification now has a verified GPU runtime path.

- Final Conda environment: `camera-service-gpu`
- Environment path: `E:\MathModelingTools\conda-envs\camera-service-gpu`
- Python: `3.10.20`
- ONNX Runtime: `onnxruntime-gpu==1.23.2`
- EfficientNet-B0 active provider: `CUDAExecutionProvider`
- Binary sample FPS remains: `POST_FALL_V2_SAMPLE_FPS=3`
- Binary input queue: `POST_FALL_V2_QUEUE_SIZE=1` so the worker keeps the newest sampled frame instead of accumulating old frames
- WebRTC target FPS: `WEBRTC_VIDEO_FPS=15`
- Startup behavior: service startup does not auto-enable binary classification
- Stream behavior: connecting video does not auto-enable binary classification
- Model behavior: binary model loads only after manual enable
- Legacy YOLO/fall-hint/tracking/pose demo flags are explicitly disabled in `.env`, `.env.example`, and `configs/safe_demo.env`

## Environment Selection

Initial audit found 11 Conda environments. None had ONNX Runtime `CUDAExecutionProvider` available before remediation.

Full environment audit summary:

| Environment | Path | Python | ORT | CUDA EP | Torch CUDA | Missing required deps | Class | Conclusion |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `AI` | `C:\Users\YANG\.conda\envs\AI` | `3.10.20` | `1.23.2` | no | yes | none | C | Best clone base: project deps present and Torch CUDA works, but ORT was CPU only |
| `ai_exam_py39` | `C:\Users\YANG\.conda\envs\ai_exam_py39` | `3.9.25` | `1.19.2` | no | no | `uvicorn`, `av`, `aiortc` | D | Not suitable for direct project GPU runtime |
| `factory` | `C:\Users\YANG\.conda\envs\factory` | `3.12.13` | n/a | no | n/a | core runtime deps | D | Not suitable for direct project runtime |
| `fall-media-demo` | `C:\Users\YANG\.conda\envs\fall-media-demo` | `3.11.15` | n/a | no | n/a | `fastapi`, `uvicorn`, `av`, `aiortc` | D | Not suitable for direct project GPU runtime |
| `health` | `C:\Users\YANG\.conda\envs\health` | `3.11.15` | `1.24.3` | no | n/a | `av`, `aiortc` | D | Not suitable for direct project GPU runtime |
| `health-diagnostics` | `C:\Users\YANG\.conda\envs\health-diagnostics` | `3.11.15` | n/a | no | n/a | core runtime deps | D | Not suitable for direct project runtime |
| `helth` | `C:\Users\YANG\.conda\envs\helth` | `3.11.15` | `1.24.3` | no | no | `av`, `aiortc` | D | Not suitable for direct project GPU runtime |
| `llamafactory` | `C:\Users\YANG\.conda\envs\llamafactory` | `3.10.20` | `1.23.2` | no | n/a | `av`, `aiortc` | D | Not suitable without modifying another project environment |
| `torchgpu` | `C:\Users\YANG\.conda\envs\torchgpu` | `3.10.20` | `1.23.2` | no | n/a | none | C | CPU-compatible fallback candidate, but no ORT CUDA EP |
| `base` | `D:\Anaconda` | `3.9.13` | `1.19.2` | no | no | none | C | CPU-compatible but older Python/ORT and no ORT CUDA EP |
| `mm2026` | `E:\MathModelingTools\conda-envs\mm2026` | `3.11.15` | n/a | no | n/a | core runtime deps | D | Not suitable for direct project runtime |

Audit artifacts:

- `artifacts/environment_audit/conda_env_audit.json`
- `artifacts/environment_audit/conda_env_audit_summary.json`

Best candidate environments:

| Environment | Path | Result |
| --- | --- | --- |
| `AI` | `C:\Users\YANG\.conda\envs\AI` | Python 3.10.20, project deps present, Torch CUDA works, ORT CPU only |
| `torchgpu` | `C:\Users\YANG\.conda\envs\torchgpu` | Python 3.10.20, project deps present, Torch CUDA works, ORT CPU only |
| `base` | `D:\Anaconda` | Project deps mostly present, Python 3.9.13, ORT CPU only |
| others | various | Missing core runtime deps or incompatible for direct use |

Decision: clone `AI` to `camera-service-gpu`, then minimally replace CPU ONNX Runtime with GPU ONNX Runtime in the clone.

Original `.venv`, `AI`, and `torchgpu` were preserved.

## Installation Facts

Performed after the audit phase:

- `conda create --name camera-service-gpu --clone AI -y`
- In `camera-service-gpu` only:
  - uninstalled `onnxruntime==1.23.2`
  - installed `onnxruntime-gpu==1.23.2`

`onnxruntime-gpu` was not present in pip cache, so pip downloaded the 244.5 MB wheel. Other package requirements were already satisfied.

## Model Validation

Artifacts:

- `artifacts/environment_audit/current_venv_efficientnet_cpu_dummy_inference.json`
- `artifacts/environment_audit/camera_service_gpu_efficientnet_dummy_inference.json`

Dummy inference comparison:

| Runtime | Active provider | Average latency |
| --- | --- | ---: |
| `.venv` | `CPUExecutionProvider` | `11.484 ms` |
| `camera-service-gpu` | `CUDAExecutionProvider` | `5.509 ms` |

The GPU validation used the real model:

`models/post_fall_v2/efficientnet_b0/fall_candidate_efficientnet_b0.onnx`

## Mock Runtime Benchmark

Artifacts:

- `artifacts/environment_audit/mock_venv_video_only.summary.json`
- `artifacts/environment_audit/mock_venv_cpu_r2.summary.json`
- `artifacts/environment_audit/mock_conda_gpu_r2.summary.json`
- `artifacts/environment_audit/mock_venv_cpu_latest_queue1.summary.json`
- `artifacts/environment_audit/mock_conda_gpu_latest_queue1.summary.json`

| Scenario | Provider | CPU total | Binary FPS | Binary frame age | Capture FPS | IPC dropped | WebRTC target |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `.venv`, video only | none | `0.349%` | `0` | n/a | `16.41` | `0` | `15` |
| `.venv`, binary on | `CPUExecutionProvider` | `71.846%` | `2.699` | `63 ms` | `16.10` | `0` | `15` |
| `camera-service-gpu`, binary on | `CUDAExecutionProvider` | `0.766%` | `2.668` | `15 ms` | `16.38` | `0` | `15` |
| `.venv`, binary on, queue=1 | `CPUExecutionProvider` | `71.575%` | `2.611` | `78 ms` | `16.10` | `0` | `15` |
| `camera-service-gpu`, binary on, queue=1 | `CUDAExecutionProvider` | `0.634%` | `2.707` | `63 ms` | `16.24` | `0` | `15` |

This mock test supports the observed diagnosis: the severe slowdown appears when binary classification runs on CPU. Moving ONNX inference to GPU releases CPU pressure while preserving the 3 FPS sampling policy.

Mock runtime does not replace real RTSP acceptance.

After the latest queue-size change, `nvidia-smi` showed no residual Python GPU process after benchmark cleanup.

## Code Changes

| File | Change |
| --- | --- |
| `app/post_fall_v2/fall_binary_classifier_service.py` | CUDA/CPU provider selection, explicit requested/available/active provider logging, CPU fallback warning, model warm-up |
| `app/post_fall_v2/post_fall_runtime_service.py` | Runtime status now exposes provider degradation, active providers, binary latency, queue delay, and AI frame age; binary input queue drops older sampled frames when the worker lags |
| `app/post_fall_v2/fall_binary_shadow_service.py` | Passes warm-up setting into shared classifier |
| `app/post_fall_v2/frame_sampler_service.py` | Avoids one redundant full-frame copy before binary preprocessing |
| `app/camera/capture_process.py` | Moves capture write-FPS throttling before ndarray/JPEG work where possible |
| `app/streaming/media_track.py` | Applies WebRTC pacing from `WEBRTC_VIDEO_FPS` |
| `frontend_demo/app.js` | Stops JPG fallback polling when WebRTC video is healthy; keeps annotation overlay disabled |
| `frontend_demo/index.html`, `frontend_demo/app.js` | Shows binary provider, sample FPS, queue depth/drops, AI frame age, and inference latency in the model control panel |
| `app/schemas/status.py` | Adds `streaming.webrtc_target_fps` |
| `app/services/status_service.py` | Publishes `webrtc_target_fps` |
| `.env`, `.env.example`, `configs/safe_demo.env` | CUDA-first binary providers, warm-up setting, binary queue size 1, WebRTC target 15 FPS, legacy YOLO/tracking/pose disabled for this profile |
| `scripts/start_visual_gpu.ps1` | Adds explicit GPU startup entry point with provider precheck and a hard warning if CUDA is requested but unavailable |
| `scripts/check_gpu_runtime_preflight.ps1` | Runs a local no-RTSP GPU preflight: providers, EfficientNet dummy CUDA inference, app import, safe_demo validation, and temporary manual-control service diagnosis |
| `scripts/benchmark_runtime.ps1` | Adds reusable runtime benchmark for mock/local/RTSP sources |
| `scripts/benchmark_mock_runtime.ps1` | Compatibility wrapper for mock benchmark command name |
| `scripts/benchmark_real_rtsp_comparison.ps1` | Runs the real RTSP video-only, `.venv` CPU binary, and Conda GPU binary scenarios with one command and writes comparison JSON/Markdown |
| `scripts/check_runtime_acceptance.ps1` | Reads a generated comparison JSON and returns a terminal-friendly PASS/FAIL/UNKNOWN result with an exit code |
| `.vscode/tasks.json` | Adds explicit VS Code tasks for GPU preflight, GPU startup, and GPU runtime diagnosis while preserving existing `.venv` rollback tasks |

## Startup Commands

Recommended GPU startup:

```powershell
cd E:\国赛\camera-service
.\scripts\start_visual_gpu.ps1
```

Equivalent direct startup:

```powershell
cd E:\国赛\camera-service
E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Rollback startup remains available:

```powershell
cd E:\国赛\camera-service
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In rollback mode, binary classification will fall back to CPU because `.venv` only exposes `AzureExecutionProvider` and `CPUExecutionProvider`.

Chinese VS Code operator guide:

- `docs/gpu_runtime_vscode_startup_guide_zh_20260826.md`

Local preflight before manual startup:

```powershell
cd E:\国赛\camera-service
.\scripts\check_gpu_runtime_preflight.ps1
```

## GPU Troubleshooting Commands

```powershell
conda activate camera-service-gpu
python -c "import onnxruntime as ort; print(ort.__version__); print(ort.get_available_providers())"
nvidia-smi
```

One-shot local runtime diagnosis:

```powershell
cd E:\国赛\camera-service
.\scripts\diagnose_gpu_runtime.ps1
```

To save the same diagnosis as structured evidence:

```powershell
.\scripts\diagnose_gpu_runtime.ps1 `
  -JsonOut "artifacts/environment_audit/runtime_diagnosis_latest.json"
```

Use this when the browser becomes slow after enabling binary classification. It checks the GPU Conda environment, the rollback `.venv`, `nvidia-smi`, `/healthz`, `/status`, and `/runtime-control/status`, then reports whether the binary model is still unloaded, using `CUDAExecutionProvider`, or falling back to `CPUExecutionProvider`.

Project runtime provider check:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/runtime-control/status?camera_id=camera_01" |
  ConvertTo-Json -Depth 10
```

Expected after enabling binary:

```json
{
  "binary_provider": "CUDAExecutionProvider",
  "binary_provider_degraded": false,
  "binary_sample_fps": 3.0
}
```

## Latest-Frame-Only Verification

Post-Fall V2 binary sampling still targets `3 FPS`, but the worker queue now has capacity `1`.

This means:

- if inference is healthy, frames are processed at the normal 3 FPS target;
- if inference temporarily lags, older sampled frames are overwritten before the worker consumes them;
- the next binary inference is biased toward the newest available sampled frame, not a historical backlog.

Verified with:

```powershell
E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe -m pytest `
  tests/test_post_fall_v2_runtime_service.py `
  tests/test_post_fall_v2_runtime_keyframe_collection.py `
  tests/test_post_fall_v2_shadow_binary_adapter.py `
  tests/test_post_fall_v2_manual_control_and_archive.py `
  tests/test_post_fall_evidence_exporter.py `
  tests/stabilization/test_unified_status_contract.py -q
```

Result: `31 passed`.

Additional checks run after the queue change:

```powershell
E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe -m compileall -q app
E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe -c "import app.main; print('app import OK')"
```

Both passed. `git diff --check` reports only CRLF conversion warnings.

After synchronizing the safe demo profile and frontend diagnostics:

```powershell
E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe scripts\validate_config.py --profile safe_demo --json-out artifacts\environment_audit\validate_safe_demo_gpu_runtime.json
node --check frontend_demo\app.js
E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe -m pytest tests/test_post_fall_v2_runtime_service.py tests/test_post_fall_v2_manual_control_and_archive.py tests/stabilization/test_unified_status_contract.py -q
```

Results: safe_demo `PASS`, frontend syntax OK, targeted tests `20 passed`.

Manual-control startup probe artifacts:

- `artifacts/environment_audit/startup_manual_control_before_stream.json`
- `artifacts/environment_audit/startup_manual_control_after_stream.json`
- `artifacts/environment_audit/startup_manual_control_status_after_stream.json`

Probe result with `configs/safe_demo.env` on a temporary local port:

| Check | Result |
| --- | --- |
| Before stream, binary enabled | `false` |
| Before stream, binary model loaded | `false` |
| After mock stream connect, binary enabled | `false` |
| After mock stream connect, binary model loaded | `false` |
| After mock stream connect, Qwen enabled | `false` |
| Manual control mode | `true` |
| Detection worker running | `false` |
| Detection model loaded | `false` |
| Detection enabled | `false` |
| WebRTC target FPS | `15` |

Benchmark summary fields were expanded so real RTSP runs can directly report:

- CPU usage for the service process tree
- GPU utilization average/max
- GPU memory average/max
- binary provider and degraded state
- binary FPS and inference latency
- binary frame age average/max
- camera frame age average/max
- binary and camera frame age first/last/delta/slope for backlog growth checks
- camera frame age samples over 300ms and 1000ms
- capture FPS average/min
- capture IPC dropped frames
- queue max depth
- WebRTC target FPS

Verified with:

```powershell
.\scripts\benchmark_runtime.ps1 `
  -PythonPath "E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe" `
  -Label "mock_conda_gpu_summary_fields" `
  -Port 8793 `
  -DurationSeconds 8 `
  -CameraId "camera_01" `
  -SourceUrl "mock://colorbars"
```

Result artifact: `artifacts/environment_audit/mock_conda_gpu_summary_fields.summary.json`.

The real RTSP comparison wrapper was also smoke-tested against the mock source with CPU baseline skipped:

```powershell
.\scripts\benchmark_real_rtsp_comparison.ps1 `
  -SourceUrl "mock://colorbars" `
  -CameraId "camera_01" `
  -DurationSeconds 2 `
  -LabelPrefix "mock_compare_script_smoke_clean" `
  -GpuPort 8893 `
  -VideoOnlyPort 8894 `
  -VenvPort 8895 `
  -SkipCpuBaseline
```

Result artifacts:

- `artifacts/environment_audit/mock_compare_script_smoke_clean_20260826_183047.comparison.json`
- `artifacts/environment_audit/mock_compare_script_smoke_clean_20260826_183047.comparison.md`
- `artifacts/environment_audit/mock_compare_trend_smoke_20260826_183612.comparison.json`
- `artifacts/environment_audit/mock_compare_trend_smoke_20260826_183612.comparison.md`
- `artifacts/environment_audit/mock_compare_acceptance_unknown_smoke_20260826_184445.comparison.json`
- `artifacts/environment_audit/mock_compare_acceptance_unknown_smoke_20260826_184445.comparison.md`

The smoke comparison produced a clean object-shaped JSON summary, confirmed `CUDAExecutionProvider` for the GPU binary scenario, showed binary FPS near the 3 FPS target, and kept queue depth at `0`.
The acceptance smoke run reported `acceptance_status=UNKNOWN` because the CPU baseline was intentionally skipped and the 3-second smoke run had fewer than 10 samples for trend checks. CUDA provider, manual binary enablement, binary FPS, and queue depth checks passed.

The benchmark summary now includes frame-age trend fields:

- `binary_frame_age_delta_ms`
- `binary_frame_age_trend_ms_per_s`
- `camera_frame_age_delta_ms`
- `camera_frame_age_trend_ms_per_s`

These fields are intended for the real RTSP long-run acceptance question: whether `frame_age_ms` is stable, or whether it grows over time and indicates a live-frame backlog.

## Requirement Status Matrix

| Requirement | Current status | Evidence |
| --- | --- | --- |
| Preserve `.venv` as rollback | Done | `.venv` remains available; rollback command documented |
| Audit existing Conda environments before installing | Done | `artifacts/environment_audit/conda_env_audit.json`, `conda_env_audit_summary.json` |
| Prefer existing or cloned Conda resources | Done | `AI` was selected as closest base and cloned to `camera-service-gpu`; original `AI` preserved |
| Avoid broad dependency upgrade | Done | Only CPU `onnxruntime` was removed from clone and `onnxruntime-gpu==1.23.2` installed |
| Verify `CUDAExecutionProvider` exists | Done | `camera-service-gpu` provider list includes `CUDAExecutionProvider` |
| Verify EfficientNet ONNX active provider is CUDA | Done | `artifacts/environment_audit/camera_service_gpu_efficientnet_dummy_inference.json` shows active providers `CUDAExecutionProvider,CPUExecutionProvider` |
| Verify dummy inference with real input metadata | Done | Same artifact records input `batch,3,224,224`, 30 measured runs, avg `5.509 ms`, p95 `6.858 ms` |
| Keep binary sample FPS at 3 | Done | `.env`, `.env.example`, `configs/safe_demo.env`, runtime status and mock benchmark show `POST_FALL_V2_SAMPLE_FPS=3` |
| Startup does not auto-enable binary/Qwen | Done | `startup_manual_control_before_stream.json` and `startup_manual_control_after_stream.json`: binary/Qwen disabled before and after stream connect |
| Legacy YOLO/fall-hint/tracking/pose disabled in this profile | Done | safe demo config validation shows these flags disabled |
| Binary worker uses latest-frame-only semantics | Done | `POST_FALL_V2_QUEUE_SIZE=1`, queue overwrite logic, mock benchmark queue depth `0` |
| WebRTC target around 15 FPS | Done | `WEBRTC_VIDEO_FPS=15`; status reports `webrtc_target_fps=15` |
| JPG fallback does not run while WebRTC is healthy | Implemented, mock/runtime checked | Frontend code disables annotated fallback when WebRTC is healthy; browser visual validation still belongs to real acceptance |
| Capture avoids unnecessary late dropping where currently practical | Implemented | `capture_process.py` throttles before ndarray/JPEG work where possible |
| Reduce obvious binary full-frame copying | Implemented | `frame_sampler_service.py` avoids an extra full-frame copy before preprocessing |
| Mock CPU pressure improves with GPU | Done for mock | `.venv` CPU queue=1: `71.575%`; Conda GPU latest summary: `0.791%`, about `98.9%` lower in mock |
| Real RTSP CPU/GPU comparison | Pending real source | `benchmark_real_rtsp_comparison.ps1` is ready, but no reachable authorized RTSP URL has been verified |
| Real RTSP frame-age stability | Pending real source | Trend metrics and acceptance checks are ready; needs 300-second real run |
| Browser visual smoothness | Pending real source/browser observation | Requires watching real WebRTC stream |
| Real standing/moving/fall/lying/empty-scene regression | Pending physical scene | Requires authorized camera and test scene |
| Qwen real event review and main-system delivery | Pending approved real event | Existing contracts/tests remain, but real event delivery requires external endpoint/source |

## Direct Answers

1. Current final Conda environment: `camera-service-gpu` at `E:\MathModelingTools\conda-envs\camera-service-gpu`.
2. Why selected: the audit found no existing Conda environment with ONNX Runtime `CUDAExecutionProvider`; `AI` had Python `3.10.20`, project dependencies, and working Torch CUDA, so it was the safest clone base.
3. Was anything downloaded: yes. `onnxruntime-gpu==1.23.2` was downloaded because the matching wheel was not already in pip cache.
4. Were existing cache/environments reused: yes. The environment was cloned from existing `AI`; only ONNX Runtime was swapped in the clone.
5. Is EfficientNet truly running on GPU: yes for dummy/model/runtime mock validation in `camera-service-gpu`; real RTSP runtime still needs the final comparison run.
6. Active provider: `CUDAExecutionProvider` in the selected GPU environment.
7. CPU pressure reduction: mock benchmark shows `.venv` CPU binary `71.575%` vs Conda GPU binary `0.791%`, about `98.9%` lower. Real RTSP reduction is not yet measured.
8. Does real video still have sustained delay: unknown until a reachable authorized RTSP source is tested.
9. Is `frame_age_ms` stable: stable in mock short runs; real RTSP long-run stability is pending.
10. Is binary still about 3 FPS: yes. Current configs keep `POST_FALL_V2_SAMPLE_FPS=3`; mock GPU benchmark measured about `2.7-2.8 FPS`.
11. Were main-system interfaces modified: no intentional main-system URL/protocol/JSON contract change was made for this optimization.
12. Was Qwen review affected: Qwen contract/fields were not intentionally changed; real Qwen review with real event keyframes still needs acceptance.
13. Current remaining bottlenecks: real RTSP capture behavior is unverified; if CPU/frame age are still poor after GPU on real camera, the next likely bottleneck is JPEG IPC encode/decode and deeper capture-frame sharing.

## Real RTSP Benchmark Command

Preferred one-command comparison after a reachable authorized RTSP URL is available:

```powershell
cd E:\国赛\camera-service
.\scripts\benchmark_real_rtsp_comparison.ps1 `
  -SourceUrl "rtsp://<user>:<password>@<host>:<port>/<path>" `
  -CameraId "camera_01" `
  -DurationSeconds 300
```

This command runs:

1. Conda GPU environment with video only, binary disabled.
2. Original `.venv` with binary enabled, expected CPU provider.
3. Conda GPU environment with binary enabled, expected CUDA provider.

It writes per-scenario `.summary.json` and `.samples.json` files, plus:

- `artifacts/environment_audit/<label>.comparison.json`
- `artifacts/environment_audit/<label>.comparison.md`

The comparison report redacts the RTSP URL so credentials are not persisted in the generated Markdown/JSON.

The comparison output also includes machine-readable acceptance fields:

- `acceptance_status`: `PASS`, `FAIL`, or `UNKNOWN`
- `acceptance_thresholds`: the thresholds used for this run
- `acceptance_checks`: per-check status, expected value, and actual value

Default acceptance thresholds:

| Check | Default |
| --- | ---: |
| Minimum CPU drop from `.venv` CPU binary to Conda GPU binary | `50%` |
| Binary FPS lower bound | `2.4` |
| Binary FPS upper bound | `3.4` |
| Frame age average upper bound | `300 ms` |
| Positive frame-age trend upper bound | `5 ms/s` |
| Minimum samples before trend checks become hard checks | `10` |
| Binary queue depth upper bound | `1` |

For a real RTSP run, `acceptance_status=UNKNOWN` usually means an intentional comparison scenario was skipped. `FAIL` means at least one hard check contradicted the acceptance target, such as CPU fallback, binary FPS far from 3 FPS, or a growing frame-age trend.

After the comparison finishes, check the generated JSON explicitly:

```powershell
.\scripts\check_runtime_acceptance.ps1 `
  -ComparisonPath "artifacts/environment_audit/<label>.comparison.json"
```

Exit codes:

| Exit code | Meaning |
| ---: | --- |
| `0` | Acceptance `PASS` |
| `1` | Acceptance `FAIL` |
| `2` | Acceptance `UNKNOWN`, usually because a required scenario was skipped or a trend run was too short |
| `3` | Invalid or missing comparison JSON |

For short smoke runs where `UNKNOWN` is expected:

```powershell
.\scripts\check_runtime_acceptance.ps1 `
  -ComparisonPath "artifacts/environment_audit/<label>.comparison.json" `
  -AllowUnknown
```

Single-scenario commands remain useful for troubleshooting:

Use this after providing a reachable authorized RTSP URL. Do not paste credentials into public logs or screenshots.

```powershell
cd E:\国赛\camera-service
.\scripts\benchmark_runtime.ps1 `
  -PythonPath "E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe" `
  -Label "real_rtsp_gpu_001" `
  -Port 8780 `
  -DurationSeconds 300 `
  -CameraId "camera_01" `
  -SourceUrl "rtsp://<user>:<password>@<host>:<port>/<path>"
```

CPU rollback comparison:

```powershell
cd E:\国赛\camera-service
.\scripts\benchmark_runtime.ps1 `
  -PythonPath "E:\国赛\camera-service\.venv\Scripts\python.exe" `
  -Label "real_rtsp_venv_cpu_001" `
  -Port 8781 `
  -DurationSeconds 300 `
  -CameraId "camera_01" `
  -SourceUrl "rtsp://<user>:<password>@<host>:<port>/<path>"
```

Video-only baseline:

```powershell
.\scripts\benchmark_runtime.ps1 `
  -PythonPath "E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe" `
  -Label "real_rtsp_gpu_video_only_001" `
  -Port 8782 `
  -DurationSeconds 300 `
  -CameraId "camera_01" `
  -SourceUrl "rtsp://<user>:<password>@<host>:<port>/<path>" `
  -SkipBinary
```

## Real Acceptance Runbook

The real-camera acceptance procedure is now documented in:

- `docs/real_rtsp_gpu_runtime_acceptance_runbook_20260826.md`
- `docs/gpu_runtime_implementation_audit_20260826.md`

Use that runbook after a reachable authorized RTSP source is available. It combines the 300-second CPU/GPU benchmark with browser visual checks, physical scene regression, timed event archive checks, Qwen confirm/deny consistency, main-system delivery validation, and disconnect/reconnect regression.

The runbook is intentionally separate from the mock benchmark evidence because mock video and dummy inference cannot prove real RTSP latency, browser smoothness, real fall scene behavior, or external Qwen/main-system availability.

## Remaining Acceptance

The following still require real video access and cannot be proven by mock data:

- Real RTSP long-run stability
- Real CPU/GPU comparison on the camera stream
- `frame_age_ms` long-run stability under physical camera load
- Browser visual smoothness with WebRTC
- RTSP disconnect/reconnect behavior
- Standing, normal movement, real fall, intentional low posture, and empty-scene regression
- Qwen review with real event keyframes
- Main-system delivery path under an approved real event

Current local probe found `127.0.0.1:8093` not reachable, so the configured local MJPEG default source was not available for real-source testing.

# GPU Runtime Implementation Audit - 2026-08-26

This audit maps the requested implementation plan to current evidence.
It is intentionally conservative: real RTSP, browser, physical scene, Qwen, and main-system checks remain incomplete until they are proven with an authorized live source.

## Step Audit

| Step | Requirement | Status | Evidence |
| ---: | --- | --- | --- |
| 1 | Save current `.venv` baseline | Done | `artifacts/environment_audit/current_venv_freeze.txt`, `.venv` provider check artifact |
| 2 | Detect NVIDIA GPU | Done | `nvidia-smi` captured in benchmark artifacts; GPU dummy inference artifact exists |
| 3 | List all Conda environments | Done | `artifacts/environment_audit/conda_env_audit.json` |
| 4 | Automatically audit Conda environments | Done | `artifacts/environment_audit/conda_env_audit_summary.json` lists 11 audited envs |
| 5 | Filter existing GPU-capable environments | Done | audit found no original env with `CUDAExecutionProvider` |
| 6 | Test candidate EfficientNet ONNX GPU inference | Done | `artifacts/environment_audit/camera_service_gpu_efficientnet_dummy_inference.json` |
| 7 | Test candidate project import/start compatibility | Done | project import and safe-demo validation passed in GPU env |
| 8 | Reuse existing env or clone closest env | Done | cloned existing `AI` into `camera-service-gpu`; preserved `.venv`, `AI`, and `torchgpu` |
| 9 | Ensure `CUDAExecutionProvider` truly works | Done for model/mock | active provider is `CUDAExecutionProvider`; real RTSP still pending |
| 10 | Modify Post-Fall V2 provider selection | Done | `FallBinaryClassifierService` selects configured providers and reports requested/available/active providers |
| 11 | Add GPU warm-up | Done | classifier warm-up uses model input metadata; no business event path is invoked |
| 12 | Keep binary at 3 FPS | Done | `.env`, `.env.example`, and `configs/safe_demo.env` keep `POST_FALL_V2_SAMPLE_FPS=3` |
| 13 | Check/fix realtime frame backlog | Done for binary queue | `POST_FALL_V2_QUEUE_SIZE=1` and latest-frame overwrite logic |
| 14 | Handle WebRTC/JPG fallback duplicate work | Implemented | frontend disables JPG fallback while WebRTC is healthy; real browser observation pending |
| 15 | Make WebRTC target about 15 FPS | Done | `WEBRTC_VIDEO_FPS=15` and `LatestFrameVideoTrack` pacing |
| 16 | Avoid useless capture processing before dropping | Implemented | capture process throttles before ndarray/JPEG work where practical |
| 17 | Reduce obvious large-frame copy before binary | Implemented | sampler keeps packet frame reference instead of redundant full-frame copy |
| 18 | Performance test | Done for dummy/mock; pending real RTSP | mock CPU/GPU comparison exists; real script ready |
| 19 | Real Post-Fall V2 chain regression | Pending real source | requires authorized RTSP, physical scenes, Qwen endpoint, and main-system endpoint |
| 20 | Output complete report | Mostly done | `docs/gpu_runtime_optimization_report_20260826.md`; final real acceptance values remain pending |

## Non-RTSP Evidence Snapshot

| Area | Evidence |
| --- | --- |
| Final env | `camera-service-gpu` at `E:\MathModelingTools\conda-envs\camera-service-gpu` |
| Rollback env | `.venv` still exists and remains CPU fallback |
| GPU provider | `CUDAExecutionProvider` available in `camera-service-gpu` |
| Model latency | dummy EfficientNet 30-run avg `5.509 ms`, p95 `6.858 ms` |
| `.venv` provider | `.venv` exposes `AzureExecutionProvider`, `CPUExecutionProvider` only |
| Mock CPU pressure | `.venv` CPU binary about `71.575%`; Conda GPU binary about `0.791%` in mock comparison |
| Manual model control | startup/stream probes show binary and Qwen are not auto-enabled |
| Safe demo profile | config validation `PASS` |
| Current focused tests | `22 passed` |
| Local GPU preflight helper | `scripts/check_gpu_runtime_preflight.ps1` runs provider checks, EfficientNet CUDA dummy inference, `app.main` import, safe_demo validation, and temporary manual-control service diagnosis |
| Local diagnosis helper | `scripts/diagnose_gpu_runtime.ps1` checks providers, service status, frame age, queue depth, and binary provider fallback without starting models; `-JsonOut` saves structured evidence |
| VS Code operator guide | `docs/gpu_runtime_vscode_startup_guide_zh_20260826.md` documents the GPU startup command, rollback risk, manual model enable flow, and lag diagnosis path in Chinese |
| VS Code tasks | `.vscode/tasks.json` exposes `GPU Runtime Preflight`, `Run Vision Service GPU (8000)`, and `Diagnose GPU Runtime (8000)` so the GPU path is visible from the command palette |

Latest local verification in this audit pass:

| Check | Result |
| --- | --- |
| GPU env ORT providers | `['TensorrtExecutionProvider', 'CUDAExecutionProvider', 'CPUExecutionProvider']` |
| GPU env project import | `app import OK` |
| `.venv` ORT providers | `['AzureExecutionProvider', 'CPUExecutionProvider']` |
| Residual GPU compute process check | `nvidia-smi --query-compute-apps=...` returned no rows |
| Diagnosis script, service unreachable path | exits cleanly and reports `service_status=unreachable` |
| Diagnosis script, temporary healthy service | reports `binary_model_loaded=False`, `binary_sample_fps=3`, `streaming.webrtc_target_fps=15`, and `binary_provider_status=not_loaded` before stream/manual enable |
| Diagnosis script JSON output, unreachable path | `artifacts/environment_audit/diagnose_gpu_runtime_unreachable_latest.json` records `service_status=unreachable`, GPU CUDA available, and `.venv` CUDA unavailable |
| Diagnosis script JSON output, healthy service | `artifacts/environment_audit/diagnose_gpu_runtime_healthy_latest.json` records `service_status=reachable`, `binary_provider_status=not_loaded`, `binary_sample_fps_status=around_3_fps`, and `queue_status=latest_frame_queue_ok_or_idle` |
| GPU runtime local preflight | `artifacts/environment_audit/gpu_runtime_preflight_20260826_192603.json` reports `PASS` for GPU provider, `.venv` baseline, EfficientNet CUDA dummy inference, `app.main` import, safe_demo config, and temporary service manual-control state |
| GPU runtime local preflight after VS Code task wiring | `artifacts/environment_audit/gpu_runtime_preflight_20260826_193031.json` reports `PASS` for the same provider, model, config, and manual-control checks |

## Completion Boundary

The full requested objective is not complete until the following have real evidence:

- 300-second real RTSP comparison with `.venv` CPU baseline and Conda GPU binary;
- `check_runtime_acceptance.ps1` returns `PASS` for that real comparison;
- browser visual inspection confirms no growing delay and no red/green realtime overlay boxes;
- physical scene regression covers empty, standing, normal movement, real fall, and low posture;
- binary full event count matches completed Qwen confirm plus deny events during the timed test;
- Qwen keyframes and JSON artifacts are present for completed reviews;
- main-system delivery accepts or dry-runs an approved real fall event without contract changes;
- RTSP disconnect/reconnect does not leave stale queues or duplicate workers.

Until those are complete, report real RTSP latency and final end-to-end acceptance as pending rather than passed.

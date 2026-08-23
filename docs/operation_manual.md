# Operation Manual

Date: 2026-07-20

## Start Stable Demo

```powershell
.\scripts\start_safe_demo.ps1
```

Default URL:

```text
http://127.0.0.1:8000/demo
```

## Check Status

```powershell
Invoke-RestMethod http://127.0.0.1:8000/healthz
Invoke-RestMethod http://127.0.0.1:8000/status
```

Interpretation:

- `/healthz` means the HTTP process is alive
- `/status` means the business vision chain state

Camera problems should appear in `/status`, not be hidden behind `/healthz`.

## Run Smoke

```powershell
python scripts/run_stable_smoke.py --profile safe_demo
```

Smoke reports are written under:

```text
artifacts/stable_smoke/
```

## Run Startup Shutdown Gate

```powershell
python scripts/run_startup_shutdown_gate.py --profile safe_demo --port 8012 --cycles 3
```

Gate reports are written under:

```text
artifacts/stabilization/S2_STARTUP_SHUTDOWN_AND_PROCESS_STABILITY/
```

## Run Camera Stream Gate

```powershell
python scripts/run_camera_stream_gate.py --profile safe_demo --port 8013
```

Gate reports are written under:

```text
artifacts/stabilization/S3_CAMERA_AND_VIDEO_STREAM_RESILIENCE/
```

## Run AI Pipeline Resilience Tests

```powershell
python -m pytest tests\stabilization\test_pose_disabled.py tests\stabilization\test_temporal_warmup.py tests\stabilization\test_inference_exception.py tests\stabilization\test_pipeline_backpressure.py tests\stabilization\test_frame_alignment.py -q --maxfail=1
```

The S4 contracts are documented in:

```text
docs/stabilization/s4_ai_pipeline_resilience.md
docs/stabilization/module_lifecycle_contract.md
docs/stabilization/frame_alignment_contract.md
```

## Run Unified Status Tests

```powershell
python -m pytest tests\stabilization\test_unified_status_contract.py -q --maxfail=1
```

The S5 contract is documented in:

```text
docs/stabilization/s5_unified_status_contract.md
```

## Build Release Bundle

```powershell
.\scripts\build_release_bundle.ps1
```

The default bundle contains source code, stable configs, stable scripts, docs, model manifest, dependency lock, and smoke evidence. Model weight files are not copied by default; include them explicitly when needed:

```powershell
.\scripts\build_release_bundle.ps1 -IncludeModels
```

## Stop Service

If started with helper script:

```powershell
.\scripts\stop_service.ps1
```

## Troubleshooting Order

1. Check process and port
2. Check `/healthz`
3. Check `/status`
4. Check camera `stream_state`
5. Check latest frame age
6. Check detector and tracking status
7. Check pose and temporal status
8. Check event reporter status
9. Check logs
10. Run smoke and inspect `summary.md`

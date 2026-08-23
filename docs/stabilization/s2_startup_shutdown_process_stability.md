# S2 Startup Shutdown And Process Stability

Date: 2026-07-20
Stage: `S2_STARTUP_SHUTDOWN_AND_PROCESS_STABILITY`

## Goal

Validate that the safe demo service can start, become observable through HTTP status endpoints, stop cleanly, and release its process and TCP port.

## Gate Command

```powershell
python scripts/run_startup_shutdown_gate.py --profile safe_demo --port 8012 --cycles 3
```

## Acceptance Boundary

`PASS` means:

- `safe_demo` config validation passes.
- The FastAPI service starts for every requested cycle.
- `/healthz` responds.
- `/status` reports `service_status=running` and `runtime_profile=safe_demo`.
- `/stream/latest-frame.jpg` returns a usable JPEG frame.
- The uvicorn process exits after termination.
- The TCP port is released after termination.

`PASS` does not mean real RTSP, synthetic fall events, incident evidence packages, WebSocket traffic, browser visuals, real delivery, Robot Assist, Go2, or Qwen/VLM were validated.

## Rollback

Remove the S2-only files added in this stage and keep the S0/S1 stable profiles and smoke unchanged. No real `.env` or production credentials are modified by this stage.

## Current Result

```text
PASS
```

Executed command:

```powershell
python scripts/run_startup_shutdown_gate.py --profile safe_demo --port 8012 --cycles 3
```

Evidence:

```text
artifacts/stabilization/S2_STARTUP_SHUTDOWN_AND_PROCESS_STABILITY/20260720T023159Z/summary.json
artifacts/stabilization/S2_STARTUP_SHUTDOWN_AND_PROCESS_STABILITY/20260720T023159Z/summary.md
artifacts/stabilization/S2_STARTUP_SHUTDOWN_AND_PROCESS_STABILITY/20260720T023159Z/cycle_01/status.json
artifacts/stabilization/S2_STARTUP_SHUTDOWN_AND_PROCESS_STABILITY/20260720T023159Z/cycle_02/status.json
artifacts/stabilization/S2_STARTUP_SHUTDOWN_AND_PROCESS_STABILITY/20260720T023159Z/cycle_03/status.json
```

Test summary:

```text
py_compile scripts/process_cleanup_check.py scripts/run_startup_shutdown_gate.py: PASS
pytest tests/stabilization/test_process_cleanup_check.py: PASS
S2 startup/shutdown gate, 3 cycles: PASS
```

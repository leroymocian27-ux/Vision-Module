# Known Issues And Risks

Date: 2026-07-20

## Known Issues

| ID | Status | Area | Description | Next action |
| --- | --- | --- | --- | --- |
| KI-001 | PASS | Python/Pydantic startup compatibility | Python 3.9 import blockers in `app.events.qwen_keyframe` and `app.contracts.integration_v1` were fixed during stabilization validation. | Keep py_compile and import checks in the stable gate. |
| KI-002 | PASS | Stable smoke | `safe_demo` smoke now starts the service and verifies config validation, `/healthz`, `/status`, latest frame, and latest integration result. | Preserve artifact `artifacts/stable_smoke/20260720T021030Z/summary.json`. |
| KI-003 | NOT_RUN | Real RTSP | Real camera stability is not validated by the new stable profiles. | Use `production_candidate.env` only after RTSP credentials and test window are approved. |
| KI-004 | NOT_IN_SCOPE | Real delivery | Real POST delivery is disabled and excluded from stable gate. | Keep disabled until separate staging/canary contract exists. |
| KI-005 | NOT_IN_SCOPE | VLM/Qwen | VLM and keyframe advisory are disabled in stable profiles. | Reintroduce only after stable v1 baseline passes. |
| KI-006 | NOT_IN_SCOPE | Robot/Go2 | Robot Assist and Go2 control are disabled and hidden by default. | Treat as post-v1 extension. |
| KI-007 | NOT_RUN | Event evidence | Synthetic fall event and incident evidence package generation were not exercised by the first stable smoke. | Add a deterministic synthetic fall-event smoke before claiming event archive `PASS`. |
| KI-008 | NOT_RUN | Realtime UI path | WebSocket contract and browser visual checks were not exercised by the first stable smoke. | Add a lightweight WS/browser smoke after S0/S1 remains green. |
| KI-009 | PASS | Process cleanup | S2 gate completed 3 safe-demo startup/shutdown cycles and verified PID disappearance plus TCP port release after every cycle. | Preserve artifact `artifacts/stabilization/S2_STARTUP_SHUTDOWN_AND_PROCESS_STABILITY/20260720T023159Z/summary.json`. |
| KI-010 | PASS | Camera stream resilience | S3 gate verified public camera state, frame freshness, stale/no-frame safety semantics, mock pause/resume/freeze, source generation reset, latest-frame headers, and process cleanup. | Preserve artifact `artifacts/stabilization/S3_CAMERA_AND_VIDEO_STREAM_RESILIENCE/20260720T025317Z/summary.json`. |
| KI-011 | NOT_RUN | S2 extended restart | 10-cycle restart validation is deferred to stable-demo RC freeze checks. | Run `python scripts/run_startup_shutdown_gate.py --profile safe_demo --port <free-port> --cycles 10` before final RC freeze. |

## Operating Rule

Do not mark any scenario as `PASS` without an artifact path, test output, screenshot, log, or machine-readable report.

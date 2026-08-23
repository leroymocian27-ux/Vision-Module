# Stable Feature Scope Matrix

Date: 2026-07-20

| Capability | Stable version scope | Default state | Gate status |
| --- | --- | --- | --- |
| HTTP service | Required | Enabled | PASS |
| `/healthz` | Process liveness only | Enabled | PASS |
| `/status` | Main troubleshooting surface | Enabled | PASS |
| Mock camera | Required for local smoke | Enabled in `safe_demo` | PASS |
| RTSP camera | Configurable and diagnosable | Disabled in `safe_demo` | NOT_RUN |
| Latest frame | Required | Enabled | PASS |
| Person detection | Required | Enabled | PASS |
| Fall hint detection | Required | Enabled | PASS |
| Tracking | Required | Enabled | PASS |
| Pose | Optional, must degrade clearly | Disabled in `safe_demo` | PASS |
| Temporal | Optional, must expose warmup/degraded state | Disabled in `safe_demo` | PASS |
| Fall fusion | Required | Enabled by main chain | PASS |
| Event archive | Local evidence only | Disabled in `safe_demo` | NOT_RUN |
| Delivery | Dry-run only in stable scope | Disabled | NOT_IN_SCOPE |
| VLM/Qwen | Advisory only, outside stable scope | Disabled | NOT_IN_SCOPE |
| Robot Assist | Outside stable scope | Disabled | NOT_IN_SCOPE |
| Go2 control | Outside stable scope | Disabled | NOT_IN_SCOPE |
| Identity enrollment | Sidecar management | Disabled in `safe_demo` | NOT_IN_SCOPE |
| Identity auto-binding | Not stable scope | Disabled | NOT_IN_SCOPE |
| Demo | Stable capabilities only | Enabled | NOT_RUN |
| WebRTC | Video display capability | Enabled | NOT_RUN |
| WebSocket | Realtime result stream | Enabled | NOT_RUN |
| Main system POST | Requires separate approval | Disabled | NOT_IN_SCOPE |

Latest evidence:

```text
artifacts/stable_smoke/20260720T021030Z/summary.json
artifacts/stable_smoke/20260720T021030Z/status.json
```

Important boundary:

`PASS` for detection, tracking, pose, temporal, and fusion means startup/status/disabled-state behavior passed under `safe_demo`. It does not mean real RTSP, real fall events, event evidence packages, WebSocket traffic, browser UI, or real delivery were validated.

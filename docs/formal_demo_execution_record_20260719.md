# Formal Demo Execution Record 2026-07-19

## Result

```yaml
formal_demo_execution: PASS
scope: P1_synthetic_demo_acceptance_only
demo_port: 8135
actual_env_modified: false
real_main_system_post: false
event_vlm_enabled: false
ollama_called: false
production_ready: false
```

This record proves the formal demonstration path only. It is not real RTSP
stability evidence, real-algorithm `fallen_confirmed` acceptance, real
main-system delivery acceptance, or VLM admission.

## Instance Boundary

| Instance | Observed result | Boundary |
| --- | --- | --- |
| `127.0.0.1:8000` | Healthy before and after; event pipeline and VLM disabled; WebRTC and WS connected in the browser. | Existing realtime presentation remained running and was not restarted. |
| `127.0.0.1:8135` | Temporary synthetic demo passed. | Loopback only; isolated SQLite/archive; mock camera; dry-run only; VLM and main-system alert disabled. |

`8011` was occupied by an unrelated Weixin process bound to `0.0.0.0` and was
not stopped or altered. The approved loopback fallback `8135` was used and was
released automatically after the run.

## Synthetic Event Evidence

| Incident | Source | Result | Keyframes | Delivery | VLM |
| --- | --- | --- | --- | --- | --- |
| `demo-rehearsal-20260718-candidate` | `fall_candidate_support` demo seed | `fallen_candidate` synthetic review | 6/6 API `200 image/jpeg`; 6/6 browser images loaded | `dry_run_sent` | disabled; rule review |
| `demo-rehearsal-20260718-confirmed-synthetic` | `fallen_confirmed_high` demo seed | synthetic confirmed comparison only | 6/6 API `200 image/jpeg`; 6/6 browser images loaded | `dry_run_sent` | disabled; rule review |

The second record is synthetic. It must not be presented as a real
`FallFusionService` algorithm-confirmed event.

## Verified Checks

| Check | Result |
| --- | --- |
| `8000 /healthz` before and after | PASS, HTTP 200 safe health summary |
| `8000 /events/status` | PASS, event pipeline false and VLM false |
| `8135 /healthz` and `/events/status` | PASS, pipeline/ring/worker/semantic enabled; VLM false |
| Candidate and confirmed detail APIs | PASS, event detail and public-field redaction verified |
| Twelve keyframe API calls | PASS, both events times six, all `200 image/jpeg` |
| Delivery | PASS, `dry_run_sent`; no real POST |
| Candidate and confirmed manual selection | PASS, each selected through Recent Events in the browser |
| Event review UI | PASS, six cards, six loaded images, rule review, dry-run and VLM-disabled state |
| WebRTC and WebSocket | PASS, both `connected` on the live and temporary demo pages |
| Browser console | PASS, warning/error count 0 for live, candidate, and synthetic confirmed pages |
| Public-page privacy scan | PASS, no `source_url`, RTSP value, token, absolute archive path, `payload_json`, or `lock_token` text found |
| Temporary cleanup | PASS, `8135` had no listener after process exit; `8000` remained healthy |

The headless browser reported WebRTC/WS connected for `8000`, while its video
decoder exposed `readyState=0` and zero dimensions. This is a headless-browser
media-decoding limitation, not evidence that the live UI was unavailable; this
P1 gate requires connected realtime transports and does not substitute for a
real-camera visual acceptance run.

## Evidence Artifacts

- `tmp_event_visual_qa/formal_demo_execution_20260718/p1_execution_summary.json`
- `tmp_event_visual_qa/formal_demo_execution_20260718/p1_api_summary.json`
- `tmp_event_visual_qa/formal_demo_execution_20260718/p1_browser_summary.json`
- `tmp_event_visual_qa/formal_demo_execution_20260718/p1_live_8000.png`
- `tmp_event_visual_qa/formal_demo_execution_20260718/p1_candidate_1366.png`
- `tmp_event_visual_qa/formal_demo_execution_20260718/p1_confirmed_synthetic_1366.png`

## Next State

```yaml
P1: PASS
P2: WAITING_FOR_APPROVAL_RESTART_8000
P3: WAITING_FOR_AUTHORIZED_REAL_RTSP
P4: WAITING_FOR_REAL_OR_REPLAY_CONFIRMED_SOURCE
P5: WAITING_FOR_REAL_STREAM_KEYFRAME_ACCEPTANCE
P6: WAITING_FOR_STAGING_CONTRACT_AND_APPROVAL
```

No P2-P6 activity was performed during this run.

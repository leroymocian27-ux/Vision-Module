# P1 Synthetic Demo Acceptance Closure

Date: 2026-07-19  
Result: `PASS`  
Scope: local synthetic formal-demo acceptance only

## Verified Boundary

| Instance | Result | Allowed purpose |
| --- | --- | --- |
| `8000` | Healthy before and after; event pipeline and VLM disabled. | Existing realtime presentation; not restarted or reconfigured. |
| `8135` | Temporary synthetic demo completed and released. | Event-review UI, evidence display and dry-run delivery demonstration. |

`8011` was occupied by an unrelated Weixin process. It was not stopped or
altered. The approved loopback replacement `8135` was used and had no listener
after acceptance.

## Evidence Result

- `demo-rehearsal-20260718-candidate`: synthetic candidate, API and UI each
  verified six keyframes; rule review and `dry_run_sent` passed.
- `demo-rehearsal-20260718-confirmed-synthetic`: synthetic comparison record,
  API and UI each verified six keyframes; rule review and `dry_run_sent` passed.
- Both pages reached WebRTC and WebSocket `connected`; browser warning/error
  count was zero; page safety checks found no raw source URL, token, local path,
  payload JSON or lock token.
- `.env` SHA256 before and after was unchanged. No real POST, VLM/Ollama call,
  image-model input, or main-system alert was enabled.

Primary evidence is recorded in
`docs/formal_demo_execution_record_20260719.md` and the referenced isolated
artifacts under `tmp_event_visual_qa/formal_demo_execution_20260718/`.

## Non-Claims

- The synthetic confirmed record is not real `FallFusionService` algorithm
  confirmation and must never be described as such.
- `dry_run_sent` proves a local DeliveryOutbox transition only; it is not a
  main-system alert.
- This result does not approve real RTSP, real replay, real POST, VLM/Ollama,
  image input, Kafka, Redis, Celery, or production enablement.

## Current State

```yaml
P1: PASS
P2: WAITING_FOR_APPROVAL_RESTART_8000
P3_P5: WAITING_FOR_AUTHORIZED_REAL_RTSP_OR_REPLAY
P6: WAITING_FOR_STAGING_CONTRACT_AND_APPROVAL
```

Next: prepare P2 only. A restart may occur solely after the user explicitly
states `批准重启 8000`.

# P6 Main-System Staging Contract Plan

Status: `WAITING_FOR_STAGING_CONTRACT_AND_APPROVAL`  
Date: 2026-07-19  
No POST is performed by this plan.

## Required Staging Contract

The main-system owner must provide, approve and version:

| Item | Required decision |
| --- | --- |
| Endpoint | Staging HTTPS endpoint and approved network route. |
| Authentication | Header name, secret-store method, token rotation and any certificate requirement. |
| Request | JSON schema, required/optional fields, size limits and forbidden fields. |
| Acknowledgement | Exact 2xx body/schema and correlation field. Current code treats any 2xx as sent, so stricter acknowledgement requires an approved code change. |
| Idempotency | Receiver behavior for repeated `incident_id`, including timeout-after-accept scenarios. |
| Timing | Timeout, retry limit, retry/backoff and receiver SLA. |
| Errors | 4xx/5xx/retryable classification, response body policy and support contact. |

## Current Delivery Contract

`DeliveryOutbox` builds a JSON event containing stable `incident_id`, camera,
event/state/status/risk, fall scores, timestamp, bbox, snapshot URL when safe,
injury/action/explanation, `delivery_mode`, `dry_run`, degradation and review
fields. `incident_id` is unique in the SQLite DeliveryOutbox and is the
receiver idempotency key. Never send raw archive paths, keyframe file paths,
tokens, lock fields or provider payloads.

When both `MAIN_SYSTEM_ALERT_TOKEN_HEADER` and `MAIN_SYSTEM_ALERT_TOKEN` are
configured, DeliveryOutbox sends that header. With either value absent it sends
no empty or guessed header. This mirrors `FallEventReporterService` while
keeping its code and role intact.

## Admission Sequence

1. **Dry-run**: no HTTP POST; prove `dry_run_sent`, persistence and API status.
2. **Loopback mock**: exercise 2xx, 5xx, timeout, invalid response, retry,
   failed and SQLite lease behavior.
3. **Isolated staging**: explicit approval, approved secret delivery, receiver
   acknowledgement and idempotency verification.
4. **Single-camera canary**: explicit approval, named camera and observation
   window. Choose one authoritative sender to avoid duplicate legacy/new alerts.
5. **Production expansion**: separate approval after canary evidence.

Every transition requires approvals from the vision owner, main-system owner,
security/operations owner and project lead. No real production endpoint may be
used before all prior gates pass.

## Rollback

First stop lease claims, then return the sidecar to dry-run or disabled:

```dotenv
EVENT_DELIVERY_WORKER_ENABLED=false
EVENT_DELIVERY_ENABLED=false
EVENT_DELIVERY_MODE=dry_run
```

Preserve SQLite records for reconciliation. Do not delete or replace
`FallEventReporterService`; restore only its previously approved state under
the legacy alert owner. Recheck realtime WebRTC, WS and REST after rollback.

## Decision Rules

- `PASS`: approved staging receiver acknowledges idempotent events, auth and
  retry behavior match contract, no duplicate alert and no realtime regression.
- `REVISE`: contract or handling gap is bounded and documented; remain in
  dry-run/mock.
- `BLOCKED`: missing contract/approval, secret risk, non-idempotent receiver,
  duplicate alert risk or realtime impact.

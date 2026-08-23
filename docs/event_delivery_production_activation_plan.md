# Event Delivery Production Activation Plan

Status: planning and configuration review only  
Date: 2026-07-18  
Production POST authorization: not granted  
Current decision: do not enable `EVENT_DELIVERY_MODE=post` against a real main system

## Scope and Non-Negotiable Boundary

`DeliveryOutbox` is an optional event-semantic side path. It does not replace
or delete `FallEventReporterService`, which remains the existing formal alert
implementation. No real target URL, token, or production environment was used
to prepare this plan.

The default configuration remains closed:

```dotenv
EVENT_DELIVERY_ENABLED=false
EVENT_DELIVERY_MODE=dry_run
EVENT_DELIVERY_BACKEND=memory
EVENT_DELIVERY_WORKER_ENABLED=false
```

## Existing Main-System Contract

The current `FallEventReporterService` defines the existing integration shape:

| Requirement | Current contract / production requirement |
| --- | --- |
| Endpoint | `MAIN_SYSTEM_BASE_URL` plus `MAIN_SYSTEM_FALL_EVENT_PATH`; existing default path is `/video-bridge/fall-events`. Confirm the final HTTPS URL with the main-system owner. |
| Method | `POST` with a JSON body. `requests` supplies `Content-Type: application/json` for `json=payload`. |
| Payload | Event contract documented in `docs/event_delivery_contract.md`; receiver must accept the stable `incident_id`, camera/event/state/status/risk fields, time, injury and action fields. |
| Legacy auth | `FallEventReporterService` sends `{MAIN_SYSTEM_ALERT_TOKEN_HEADER: MAIN_SYSTEM_ALERT_TOKEN}` only when both values are non-empty. Default header name is `X-Vision-Service-Token`. Confirm the real token scheme, rotation policy, and whether mutual TLS or an API gateway is required. |
| Timeout | Both old reporter and DeliveryOutbox use `MAIN_SYSTEM_ALERT_TIMEOUT_MS / 1000`, with a minimum of 0.2 seconds. Choose a production value jointly with the main-system owner; do not use the short mock timeout. |
| Delivery retries | DeliveryOutbox retries non-2xx responses and `requests` exceptions. Default limit is `3`; default fixed backoff is `5` seconds. A record then becomes `failed`. It is not exponential backoff. |
| Idempotency | SQLite has a unique `incident_id` per DeliveryRecord. The main system must also treat `incident_id` as an idempotency key because a timeout can occur after it has accepted a request. |
| Success semantics | Current DeliveryOutbox treats any HTTP 2xx as success; it has no required response-body/JSON schema. Formal receiver acknowledgement semantics remain a main-system integration decision. |

## Authentication Readiness Before Production POST

P8 added the legacy-compatible optional token header to
`DeliveryOutbox.deliver()`. When both `MAIN_SYSTEM_ALERT_TOKEN_HEADER` and
`MAIN_SYSTEM_ALERT_TOKEN` are non-empty, it sends that header with the POST.
When either is empty, it sends no authentication header. Payload JSON is
unchanged.

Do **not** point `EVENT_DELIVERY_TARGET_URL` at the real main system until all
of the following are complete and approved:

1. Main-system owner supplies the final endpoint, authentication method,
   required headers, certificate requirements, and success/error response
   contract.
2. The configured header/token pair is reviewed and mock-tested without logging
   token values.
3. The main system proves idempotent handling of repeated `incident_id` values.
4. Security owner approves the network route and secret storage mechanism.

## Pre-Enable Checklist

All items require an owner sign-off before the next stage.

- [ ] Main-system endpoint is an approved HTTPS endpoint, not an IP discovered at runtime.
- [ ] HTTP method, required JSON fields, response success condition, and error body policy are documented.
- [ ] Authentication contract is supplied; token is stored in the approved secret store, not committed to `.env.example`, logs, or screenshots.
- [ ] DeliveryOutbox header/auth support has been implemented and mock-tested against that contract.
- [ ] Receiver deduplicates `incident_id`; an accepted replay returns a defined idempotent success response.
- [ ] `EVENT_DELIVERY_SQLITE_PATH` is on a durable, writable volume with backup/retention ownership.
- [ ] `/events/delivery/status`, `/events/delivery/outbox`, and alerting log collection are available to the operations owner.
- [ ] Failure, retry, disk-full, SQLite-lock, and process-restart behavior have passed in the target environment.
- [ ] The legacy alert owner has selected one authoritative outbound sender for the canary to avoid duplicate alerts.
- [ ] A rollback operator, a main-system contact, and a monitoring window are scheduled.
- [ ] `FallEventReporterService` remains deployed and its configuration is recorded before changes.

## Staged Activation

Each stage has an explicit stop condition. Do not skip stages.

### 1. SQLite Dry-Run

Use a controlled camera or replay source. No HTTP traffic is allowed.

```dotenv
EVENT_PIPELINE_ENABLED=true
EVENT_RING_BUFFER_ENABLED=true
EVENT_WORKER_ENABLED=true
EVENT_SEMANTIC_ENABLED=true
EVENT_DELIVERY_ENABLED=true
EVENT_DELIVERY_MODE=dry_run
EVENT_DELIVERY_BACKEND=sqlite
EVENT_DELIVERY_SQLITE_PATH=data/event_delivery_outbox.sqlite3
EVENT_DELIVERY_WORKER_ENABLED=true
EVENT_DELIVERY_TARGET_URL=

MAIN_SYSTEM_ALERT_ENABLED=false
EVENT_VLM_ENABLED=false
```

Pass criteria: a DeliveryRecord reaches `dry_run_sent`, survives restart, and
all `/events/delivery/*` endpoints report the same incident. See
`docs/event_delivery_dry_run_acceptance_20260718.md`.

### 2. Loopback Mock POST

Target only the loopback mock server from P4, never a real address.

```dotenv
EVENT_DELIVERY_MODE=post
EVENT_DELIVERY_BACKEND=sqlite
EVENT_DELIVERY_WORKER_ENABLED=true
EVENT_DELIVERY_TARGET_URL=http://127.0.0.1:<mock-port>/success
MAIN_SYSTEM_ALERT_ENABLED=false
```

Pass criteria: 200, 500, timeout, retry, failed, lock lease and backoff cases
pass. See `docs/event_delivery_mock_post_acceptance_20260718.md`.

### 3. Single-Camera Production Canary

This stage requires explicit written authorization after the blocking auth gap
is closed. Enable one named, approved camera only. Keep all other cameras on
dry-run or delivery-disabled. The configuration below is a template, not an
instruction to execute now:

```dotenv
EVENT_DELIVERY_ENABLED=true
EVENT_DELIVERY_MODE=post
EVENT_DELIVERY_BACKEND=sqlite
EVENT_DELIVERY_SQLITE_PATH=<approved-durable-path>
EVENT_DELIVERY_WORKER_ENABLED=true
EVENT_DELIVERY_TARGET_URL=https://<approved-main-system>/<approved-path>
EVENT_DELIVERY_RETRY_LIMIT=3
EVENT_DELIVERY_RETRY_BACKOFF_SECONDS=5
EVENT_DELIVERY_CLAIM_TTL_SECONDS=30
MAIN_SYSTEM_ALERT_ENABLED=false
```

Before switching, preserve the old reporter configuration and agree whether it
remains enabled in dry-run only or disabled for that camera. Do not operate the
legacy reporter and DeliveryOutbox as two real senders to the same endpoint
unless the receiver has explicitly approved duplicate traffic.

Canary pass criteria: receiver acknowledgement is correlated by `incident_id`,
there are no unexpected retries/failed records, no duplicate downstream alert,
and realtime WebRTC/WS/REST publication remains healthy throughout the agreed
observation window.

### 4. Full Production POST

Proceed only after the canary owner signs off. Expand the approved camera scope
in small batches with monitoring after every batch. Keep SQLite outbox backups,
delivery API metrics, and rollback access available. Stop expansion immediately
on authentication failure, duplicate alert, elevated retry/failed count, or any
realtime regression.

## Commands and Configuration Handling

Use the approved deployment configuration store. The following PowerShell
commands are templates for a controlled service session only; replace
placeholders after approval and never place a real token in shell history.

```powershell
# Dry-run verification only. This does not contact the main system.
$env:EVENT_DELIVERY_ENABLED = 'true'
$env:EVENT_DELIVERY_MODE = 'dry_run'
$env:EVENT_DELIVERY_BACKEND = 'sqlite'
$env:EVENT_DELIVERY_WORKER_ENABLED = 'true'
$env:MAIN_SYSTEM_ALERT_ENABLED = 'false'
.\.venv\Scripts\python.exe -m pytest tests\test_event_delivery_dry_run_acceptance.py -q
```

```powershell
# Loopback mock-post verification only. Do not replace the target with production.
.\.venv\Scripts\python.exe -m pytest tests\test_event_delivery_mock_post_acceptance.py -q
```

Formal production `post` configuration is intentionally limited to the template
above until the named authorization and authentication prerequisites are met.

## Rollback

Rollback has priority over retry completion. First stop new retry claims, then
disable the delivery side path. Preserve the SQLite file for diagnosis; do not
delete or edit records during an incident.

```dotenv
EVENT_DELIVERY_WORKER_ENABLED=false
EVENT_DELIVERY_ENABLED=false
EVENT_DELIVERY_MODE=dry_run
```

Apply the configuration through the approved deployment mechanism and restart
the service once. Confirm:

1. `/events/delivery/status` reports `event_delivery_enabled=false` and
   `worker_running=false`.
2. `/events/delivery/outbox` is retained for investigation but no records move
   to `sending`.
3. `FallEventReporterService` code and configuration remain intact. Restore its
   previous approved state only under the legacy alert owner's direction.
4. Realtime result, WebRTC, WebSocket, and REST health checks remain normal.

## Acceptance Criteria for a Future Production Decision

- Main-system authentication and response contract are implemented and signed off.
- Receiver idempotency is verified with the same `incident_id` sent more than once.
- One-camera canary sends only authorized events and produces no duplicate alert.
- `sent`, `retry`, and `failed` counts are reconciled against receiver logs.
- Timeout, 5xx, restart, lock-expiry, and rollback drills succeed.
- There is no material degradation in detection latency, websocket delivery,
  REST latest-result freshness, or WebRTC playback during the canary.

## Risks and Responsible Roles

| Risk | Mitigation | Responsible role |
| --- | --- | --- |
| Duplicate alerts from legacy and new senders | Designate one authoritative production sender per camera before canary. | Alert integration owner |
| Unauthorized POST or token leakage | Do not enable production post until header/auth support and secret storage are approved. | Security owner + backend owner |
| Lost or duplicate event after timeout | Receiver enforces `incident_id` idempotency; retain SQLite outbox. | Main-system backend owner |
| Retry backlog or SQLite capacity issue | Monitor counts, disk, backup and cleanup ownership; use rollback first. | Operations owner |
| Delivery worker affects realtime | Keep it side-path only; monitor WS/REST/WebRTC and stop worker on regression. | Vision-service owner |
| Unclear incident response authority | Assign named people to each role before Stage 3. | Project lead |

Named people have not been supplied in this repository. The project lead must
replace each responsible role with an accountable person and contact channel
before authorizing any production POST.

# Event Delivery Final E2E Runbook

## 1. Acceptance Goal

Prove that `DeliveryOutbox` works inside the complete event semantic pipeline, not only as an isolated unit:

- Real event-chain records can enter `DeliveryOutbox`.
- `dry_run` creates `dry_run_sent` without POST.
- Mock `post` can deliver a payload.
- Retry/failed behavior follows the delivery state machine.
- The legacy realtime and alert paths remain unchanged.

## 2. Preconditions

- Do not edit the local `.env`.
- Use temporary PowerShell environment variables for each run.
- Use SQLite for event and delivery outboxes during acceptance.
- Use `scripts/seed_event_pipeline_demo.py` or a controlled replay event.
- Keep DeliveryOutbox disabled by default outside the temporary session.
- Keep real VLM and real main-system POST disabled unless separately approved.

## 3. Dry-Run + SQLite Steps

Example session-only settings:

```powershell
$env:EVENT_PIPELINE_ENABLED="true"
$env:EVENT_WORKER_ENABLED="true"
$env:EVENT_SEMANTIC_ENABLED="true"
$env:EVENT_DELIVERY_ENABLED="true"
$env:EVENT_DELIVERY_WORKER_ENABLED="true"
$env:EVENT_DELIVERY_MODE="dry_run"
$env:EVENT_OUTBOX_BACKEND="sqlite"
$env:EVENT_OUTBOX_SQLITE_PATH="data/event_outbox.sqlite3"
$env:EVENT_DELIVERY_BACKEND="sqlite"
$env:EVENT_DELIVERY_SQLITE_PATH="data/event_delivery_outbox.sqlite3"
```

Generate a demo or replay event, then query:

```text
/events/latest?camera_id=camera_01
/events/{incident_id}
```

Pass criteria:

- A delivery record exists.
- `delivery_status=dry_run_sent`.
- `delivery_mode=dry_run`.
- `dry_run=true`.
- No HTTP POST was called.
- Recreating the outbox can still read the SQLite delivery record.

## 4. Mock Main-System POST Steps

Use a local mock receiver or pytest mock, never the real main system:

```powershell
$env:EVENT_DELIVERY_MODE="post"
$env:EVENT_DELIVERY_TARGET_URL="http://127.0.0.1:<mock-port>/video-bridge/fall-events"
```

Generate an event and run one event/delivery worker cycle.

Pass criteria:

- Mock receiver receives one payload.
- Payload includes `incident_id`, `camera_id`, `event_type`, `status`, `state`, `severity`, `risk_level`, `injury`, `delivery_mode=post`, and `dry_run=false`.
- Delivery record becomes `sent`.

## 5. Retry / Failed Steps

Use mock responses:

- HTTP 500 should produce `retry` and set `next_retry_at`.
- Timeout should produce `retry` and record a bounded `last_error`.
- After `EVENT_DELIVERY_RETRY_LIMIT`, the delivery record should become `failed`.
- Retry records must not be claimed until `next_retry_at` is due.

## 6. API Security Check

Check `/events/latest` and `/events/{incident_id}`.

Allowed delivery summary fields:

- `delivery_status`
- `delivery_mode`
- `dry_run`
- `retry_count`
- `next_retry_at`
- `last_error`
- `delivered_at`
- `delivery_backend`

Forbidden fields/content:

- `lock_token`
- internal lock fields when hidden by design
- raw `payload_json`
- auth headers or tokens
- complete internal endpoints
- local absolute paths such as Windows drive paths, `/workspace`, or archive filesystem paths

`snapshot_url` must be empty, HTTP(S), service-relative, or another safe relative API URL.

## 7. Legacy Main-Path Check

Confirm these remain unchanged:

- `FallEventReporterService` is not replaced.
- `/integration/fall-alerts/poll` behavior is unchanged.
- `FallFusionService` is unchanged.
- Realtime detection, WebRTC, WebSocket, and REST remain independent from DeliveryOutbox failures.

## 8. Real Endpoint Preconditions

Before connecting a real main-system endpoint, manually confirm:

- Endpoint URL and method.
- Authentication header and token source.
- Timeout and retry policy.
- Idempotency key and whether `incident_id` is accepted.
- Whether the main system accepts `dry_run`.
- Whether candidate, review, and confirmed event types are accepted.
- Error-code meaning and rollback plan.
- Whether duplicate delivery can create duplicate alarms.

Real POST is forbidden before this approval is complete.

## 9. Executed Service-Level Record

This service-level acceptance was executed with a temporary uvicorn process and temporary environment variables only.

```text
port=8131
incident_id=service-final-demo-a
scenario=fall_candidate_support
delivery_status=dry_run_sent
delivery_mode=dry_run
dry_run=true
retry_count=0
delivery_backend=sqlite
service_stopped=true
.env_modified=false
real_post=false
real_vlm=false
kafka_redis_celery=false
real_replay=false
```

The seeded event was created by:

```powershell
python scripts/seed_event_pipeline_demo.py `
  --db <temp>/event_outbox.sqlite3 `
  --delivery-db <temp>/event_delivery_outbox.sqlite3 `
  --archive-dir <temp>/archive `
  --camera-id camera_01 `
  --incident-id service-final-demo-a `
  --scenario fall_candidate_support `
  --seed-delivery-dry-run
```

Checked APIs:

```text
/events/status
/events/latest?camera_id=camera_01
/events/service-final-demo-a
/events/delivery/status
```

No `lock_token`, raw `payload_json`, local absolute path, auth header, or token was exposed in `/events/latest` or `/events/{incident_id}`.

Real replay was not executed in this run because the service-level dry-run/sqlite closure was completed with the dev/demo seed path. Real replay remains optional and must keep delivery in dry-run mode.

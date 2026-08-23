# Event Delivery Contract

Final frozen version note: this contract is sealed for the A-line reliable-delivery side-path handover under `DELIVERY_OUTBOX_HANDOVER_PACK_READY`. Future changes must follow `docs/event_delivery_change_guard.md`.

## Scope

`DeliveryOutbox` is an opt-in side path for the event semantic pipeline. It does not replace, bypass, or disable `FallEventReporterService`, which remains the current formal main-system fall alert channel.

Delivery is disabled by default:

```text
EVENT_DELIVERY_ENABLED=false
EVENT_DELIVERY_MODE=dry_run
EVENT_DELIVERY_BACKEND=memory
EVENT_DELIVERY_SQLITE_PATH=data/event_delivery_outbox.sqlite3
EVENT_DELIVERY_WORKER_ENABLED=false
EVENT_DELIVERY_WORKER_INTERVAL_SECONDS=2
EVENT_DELIVERY_CLAIM_TTL_SECONDS=30
EVENT_DELIVERY_TARGET_URL=
EVENT_DELIVERY_ENDPOINT=
EVENT_DELIVERY_TIMEOUT_SECONDS=2.5
EVENT_DELIVERY_RETRY_LIMIT=3
EVENT_DELIVERY_MAX_RETRIES=3
EVENT_DELIVERY_RETRY_BACKOFF_SECONDS=5
```

The event pipeline and delivery flags are independent from `MAIN_SYSTEM_ALERT_ENABLED`.

## Backends

`EVENT_DELIVERY_BACKEND=memory` keeps delivery records in process memory. This remains the default and is suitable for local dry-run checks.

`EVENT_DELIVERY_BACKEND=sqlite` stores delivery records in `EVENT_DELIVERY_SQLITE_PATH`. The SQLite backend uses one effective record per `incident_id`, persists records across service restarts, and supports lease-based `claim_next()` for retry workers. SQLite write or claim errors are caught and logged so delivery storage cannot interrupt the realtime detection path.

SQLite records include delivery id, incident id, camera id, target URL, payload JSON, delivery status, delivery mode, dry-run marker, attempt count, last HTTP status, last error, next retry time, lock owner/token/until, created/updated times, and delivered time.

## Modes

`dry_run` creates a delivery record and builds the main-system-compatible payload, but it does not send HTTP traffic. Dry-run records use:

```text
delivery_mode=dry_run
dry_run=true
delivery_status=dry_run_sent
```

`post` sends the payload only to an explicitly configured `EVENT_DELIVERY_TARGET_URL` or `EVENT_DELIVERY_ENDPOINT`. If no event delivery target URL is configured, the record moves through retry/failed with `last_error=missing_event_delivery_target_url`; it does not fall back to the legacy main-system URL. Post records move through:

```text
pending -> sending -> sent
pending -> sending -> retry
pending -> sending -> failed
```

The same `incident_id` reuses the existing delivery record instead of creating duplicate effective deliveries.

## Worker

`DeliveryWorker` is an optional lightweight in-process retry worker. It runs only when both flags are true:

```text
EVENT_DELIVERY_ENABLED=true
EVENT_DELIVERY_WORKER_ENABLED=true
```

The worker periodically calls `claim_next(worker_id, EVENT_DELIVERY_CLAIM_TTL_SECONDS)` and then `deliver(delivery_id)`. It catches and logs exceptions and is not wired into the realtime path by default. The worker does not use Kafka, Redis, Celery, APScheduler, or any other external scheduler.

## Read-Only APIs

Delivery observability is available under the existing `/events` router:

| API | Purpose |
| --- | --- |
| `GET /events/delivery/status` | Delivery flags, backend, worker state, and status counts. |
| `GET /events/delivery/outbox?status=&camera_id=&limit=` | Read-only delivery record list. |
| `GET /events/delivery/{delivery_id}` | Read-only delivery record detail. |
| `GET /events/delivery/by-incident/{incident_id}` | Read-only lookup by incident id. |

These APIs do not claim records, call `deliver()`, change retry times, or send HTTP traffic. They return a bounded `payload_summary` instead of raw `payload_json` and filter local absolute paths from public fields. Public delivery summaries expose `delivery_status`, `delivery_mode`, `dry_run`, `retry_count`, `next_retry_at`, `last_error`, `delivered_at`, and `delivery_backend`; internal `lock_token`, lock fields, target URLs, auth headers, and tokens are never exposed.

## Payload Fields

`build_main_system_payload()` aligns the event pipeline payload with the existing `FallEventReporterService` main-system alert fields:

| Field | Meaning |
| --- | --- |
| `incident_id` | Stable fall incident id. |
| `camera_id` | Source camera id. |
| `stream_name` | Currently `primary`. |
| `source` | Currently `vision_service`. |
| `event_type` | `fall_confirmed`, `fall_candidate`, or `fall_review_required`. |
| `state` | `fallen_confirmed`, `fallen_candidate`, or `need_review`. |
| `status` | `confirmed_fall`, `fall_candidate`, or `review_required`. |
| `severity` | Main-system severity code from risk mapping. |
| `risk` | Normalized risk level. |
| `risk_level` | Same normalized risk level for compatibility. |
| `fall_detected` | True for confirmed or supported fall alarms; false for unsupported review/candidate records. |
| `fall_prob` | Evidence fall probability, falling back to trusted confidence. |
| `fall_score` | Evidence score, then evidence probability, then trusted confidence. |
| `track_id` | Evidence track id as a string when present. |
| `bbox` | Trigger keyframe bbox, then another keyframe bbox, then latest bbox sequence item. |
| `snapshot_url` | HTTP(S), service-relative, or safe relative snapshot reference only. Local absolute paths are not exposed. |
| `timestamp` | Evidence trigger timestamp. |
| `injury.level` | Injury level code from risk mapping. |
| `injury.reason` | Evidence decision reason or a vision-service fallback reason. |
| `injury.advice` | Trusted recommended action. |
| `explanation` | Trusted explanation. |
| `recommended_action` | Trusted recommended action. |
| `advice` | Same as recommended action for compatibility. |
| `delivery_mode` | `dry_run` or `post`. |
| `dry_run` | True when no real POST is attempted. |
| `degradation_used` | Evidence, semantic, and trusted-result degradation markers. |
| `review_result` | Trusted review source/result marker. |

Small compatibility objects such as `scores`, `metadata.event`, and `semantics.uncertainty` may be included. Raw image bytes and local absolute archive paths are not included.

## Event Mapping

Confirmed final event types (`confirmed`, `fall_confirmed`, `fallen_confirmed`, `confirmed_fall`) map to:

```text
event_type=fall_confirmed
state=fallen_confirmed
status=confirmed_fall
```

Candidate events map to:

```text
event_type=fall_candidate
state=fallen_candidate
status=fall_candidate
```

Review events (`need_review`, `review_required`, `fall_review_required`) map to:

```text
event_type=fall_review_required
state=need_review
status=review_required
```

## Severity Mapping

| Risk | Severity |
| --- | --- |
| `critical` | `L3` |
| `high` | `L2` |
| `medium` | `L1` |
| `low` | `L0` |
| unknown or empty | `L1` |

## Injury Mapping

| Risk | `injury.level` |
| --- | --- |
| `critical` | `I3` |
| `high` | `I2` |
| `medium` | `I1` |
| `low` | `I0` |
| unknown or empty | `I1` |

## Retry And Failure

In `post` mode each send attempt increments `attempt_count`.

Non-2xx HTTP responses record `last_http_status`, set `last_error` to `http_<status>`, and move to `retry` until `EVENT_DELIVERY_RETRY_LIMIT` is reached. Request exceptions record `last_error`, keep `last_http_status=null`, and also move to `retry` until the retry limit is reached. Retry records include `next_retry_at`; records beyond the limit move to `failed`.

`claim_next()` only claims `pending` records or `retry` records whose `next_retry_at` has arrived. A claimed record receives `lock_owner`, `lock_token`, and `lock_until`; other workers cannot claim it again until the lease expires.

Final E2E acceptance is documented in `docs/event_delivery_final_e2e_runbook.md`. Real endpoint access must pass `docs/event_delivery_real_endpoint_preflight.md` first.

## Current Non-Goals

- `DeliveryOutbox` is still a side path; SQLite durability is optional and not enabled by default.
- Formal main-system delivery has not been handed over from `FallEventReporterService`.
- Kafka, Redis, Celery, and real VLM delivery participation are not introduced.

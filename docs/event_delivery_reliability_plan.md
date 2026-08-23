# Event Delivery Reliability Plan

## Current Position

DeliveryOutbox is the event semantic pipeline delivery side path. `FallEventReporterService` remains the formal main-system fall alert path. Delivery is safe by default: disabled, dry-run mode, memory backend, worker disabled.

## Capability Stages

1. Payload contract: `build_main_system_payload()` produces main-system-compatible fall alert fields for confirmed, candidate, and review events.
2. Memory outbox: supports dry-run, post, retry, failed, and per-incident deduplication inside the process.
3. SQLite outbox: optional persistence through `EVENT_DELIVERY_BACKEND=sqlite`, with one effective record per `incident_id`.
4. Retry worker: optional `DeliveryWorker`, enabled only when both delivery and worker flags are true.
5. Observability: read-only `/events/delivery/*` APIs expose status and summaries without mutating delivery state.
6. Mock integration: tests cover dry-run, post success, HTTP failure, timeout, retry, failed, and worker-driven delivery.

## Reliability Rules

- Delivery writes and worker exceptions must be caught and logged.
- Failed posts must move to `retry` or `failed`; events must not disappear silently.
- Retry claims must respect `next_retry_at` and `lock_until`.
- Dry-run must never call `requests.post`.
- SQLite persistence must not affect realtime detection or legacy alert delivery.

## Remaining Boundaries

- No Kafka, Redis, Celery, APScheduler, or real VLM delivery participation.
- No replacement of `FallEventReporterService`.
- No default production POST.
- Real main-system production cutover requires a separate rollout decision.

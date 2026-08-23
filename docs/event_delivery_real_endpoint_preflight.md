# Event Delivery Real Endpoint Preflight

## 1. Current State

- `DeliveryOutbox` supports controlled `post`.
- The real main-system endpoint is not connected.
- Delivery is disabled by default.
- `post` requires an explicit `EVENT_DELIVERY_TARGET_URL` or `EVENT_DELIVERY_ENDPOINT`; it does not reuse the legacy reporter URL implicitly.

## 2. Must Confirm Before Real Endpoint Access

- Main-system URL.
- HTTP method.
- Auth header name.
- Token source and rotation owner.
- Timeout.
- Retry limit and backoff.
- Idempotency key.
- Whether the main system accepts `incident_id`.
- Whether the main system accepts the `dry_run` marker.
- Whether candidate, review, and confirmed events are accepted.
- Main-system error-code semantics.
- Whether duplicate reports can create duplicate alarms.
- Rollback plan and operator.

## 3. Forbidden Items

- Do not hard-code endpoint URLs in code.
- Do not hard-code tokens in code.
- Do not enable `post` by default.
- Do not silently reuse the `FallEventReporterService` URL.
- Do not bypass the DeliveryOutbox state machine.
- Do not POST from realtime detection threads.
- Do not expose local absolute paths, raw image bytes, lock tokens, auth headers, or secrets.

## 4. Recommended Real Endpoint Acceptance Order

1. Dry-run.
2. Mock post.
3. Staging post.
4. Single-event real post.
5. Small-batch real post.
6. Long-running stability observation.

Each stage should keep an explicit rollback setting:

```text
EVENT_DELIVERY_ENABLED=false
EVENT_DELIVERY_WORKER_ENABLED=false
```

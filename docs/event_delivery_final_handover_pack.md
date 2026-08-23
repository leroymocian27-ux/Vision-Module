# Event Delivery Final Handover Pack

## 1. Final A-Line Conclusion

`DELIVERY_OUTBOX_SIDE_PATH_FREEZE_READY` is established.

`DELIVERY_OUTBOX_HANDOVER_PACK_READY` is established.

`DeliveryOutbox` can be handed over as the stable reliable-delivery side path for the event semantic pipeline. It is ready for overall project demo closure, while remaining default-off and separate from the formal main-system alert channel.

## 2. Current Capability List

- Memory backend.
- SQLite backend.
- `dry_run` mode.
- Controlled `post` mode.
- Retry state.
- Failed state.
- Lease claim fields for retry workers.
- `next_retry_at` retry scheduling.
- Idempotency by `incident_id`.
- Public delivery safe summary.
- Mock main-system post acceptance.
- Service-level dry-run + SQLite acceptance.
- A/B/C Final E2E guard acceptance.

## 3. Default Configuration

```text
EVENT_DELIVERY_ENABLED=false
EVENT_DELIVERY_WORKER_ENABLED=false
EVENT_DELIVERY_MODE=dry_run
EVENT_DELIVERY_BACKEND=memory
EVENT_DELIVERY_SQLITE_PATH=data/event_delivery_outbox.sqlite3
EVENT_DELIVERY_TARGET_URL=
EVENT_DELIVERY_ENDPOINT=
```

Delivery remains opt-in. `post` requires an explicit event delivery endpoint and never falls back to the legacy `FallEventReporterService` main-system URL.

## 4. DeliveryOutbox State Machine

```text
pending -> dry_run_sent
pending -> sending -> sent
pending -> sending -> retry -> sending -> sent
pending -> sending -> retry -> failed
```

Only HTTP 2xx marks a record as `sent`. Missing target URL, non-2xx HTTP, and request exceptions move records through retry/failed without dropping the event.

## 5. API Safe Summary

Allowed public delivery fields:

- `delivery_status`
- `delivery_mode`
- `dry_run`
- `retry_count`
- `next_retry_at`
- `delivered_at`
- `delivery_backend`
- redacted `last_error`

Forbidden public fields or content:

- `target_url`
- `lock_token`
- `lock_owner`
- `lock_until`
- raw `payload_json`
- auth header
- token
- local absolute paths
- provider `raw_response`
- `keyframe_image_paths`
- local `timeline_image_path`

## 6. Relationship With The Legacy Main Path

- `FallEventReporterService` remains the formal main-system alert channel.
- `DeliveryOutbox` remains an event semantic side path.
- `/integration/fall-alerts/poll` is unchanged.
- `FallFusionService` is unchanged and remains the fall decision authority.
- DeliveryOutbox errors do not affect realtime detection.

## 7. Acceptance Index

- Unit tests cover payload compatibility, memory outbox, SQLite outbox, worker, and main-system contract.
- Mock post tests cover successful `post` delivery.
- Retry/failed tests cover non-2xx, retry due time, and retry limit behavior.
- Service-level dry-run + SQLite acceptance is documented in `docs/event_delivery_final_e2e_runbook.md`.
- A/B/C Final E2E delivery guard is documented in `docs/event_delivery_abc_final_integration_ready.md`.
- Legacy reporter regression is covered by `tests/test_fall_event_reporter_service.py` and `tests/test_fall_alert_polling_api.py`.

## 8. Not Connected

- Real main-system endpoint.
- Kafka.
- Redis.
- Celery.
- Formal replacement of the current main-system alert path.


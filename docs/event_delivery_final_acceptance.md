# Event Delivery Final Acceptance

## 1. Position

`DeliveryOutbox` is an optional side path in the event semantic pipeline. It does not replace `FallEventReporterService`, which remains the formal main-system alert channel. It also does not change `FallFusionService`, realtime detection, WebRTC, WebSocket, REST, or `/integration/fall-alerts/poll`.

## 2. State Machine

```text
pending -> sending -> sent
pending -> sending -> retry -> sending -> sent
pending -> sending -> retry -> sending -> failed
pending -> dry_run_sent
```

Only HTTP 2xx marks `sent`. Non-2xx responses, request exceptions, and missing event delivery target URLs move through retry/failed without dropping the record.

## 3. Modes

`dry_run` creates a delivery record and payload, does not POST, and ends as `dry_run_sent`. `post` sends only when `EVENT_DELIVERY_ENABLED=true`, `EVENT_DELIVERY_MODE=post`, and an explicit `EVENT_DELIVERY_TARGET_URL` or `EVENT_DELIVERY_ENDPOINT` is configured.

## 4. Default-Off Configuration

```text
EVENT_DELIVERY_ENABLED=false
EVENT_DELIVERY_MODE=dry_run
EVENT_DELIVERY_BACKEND=memory
EVENT_DELIVERY_WORKER_ENABLED=false
EVENT_DELIVERY_WORKER_INTERVAL_SECONDS=2
EVENT_DELIVERY_CLAIM_TTL_SECONDS=30
EVENT_DELIVERY_SQLITE_PATH=data/event_delivery_outbox.sqlite3
EVENT_DELIVERY_TARGET_URL=
EVENT_DELIVERY_ENDPOINT=
EVENT_DELIVERY_TIMEOUT_SECONDS=2.5
EVENT_DELIVERY_RETRY_LIMIT=3
EVENT_DELIVERY_MAX_RETRIES=3
EVENT_DELIVERY_RETRY_BACKOFF_SECONDS=5
```

## 5. Payload Contract

`build_main_system_payload()` includes the main-system-compatible fields:

```text
incident_id, camera_id, stream_name, source, event_type, state, status,
severity, risk, risk_level, fall_detected, fall_prob, fall_score, track_id,
bbox, snapshot_url, timestamp, injury.level, injury.reason, injury.advice,
explanation, recommended_action, advice, delivery_mode, dry_run,
degradation_used, review_result
```

Event mapping:

```text
confirmed -> event_type=fall_confirmed, status=confirmed_fall, state=fallen_confirmed
candidate -> event_type=fall_candidate, status=fall_candidate, state=fallen_candidate
review    -> event_type=fall_review_required, status=review_required, state=need_review
```

## 6. Risk Mapping

```text
critical -> severity L3, injury.level I3
high     -> severity L2, injury.level I2
medium   -> severity L1, injury.level I1
low      -> severity L0, injury.level I0
unknown  -> severity L1, injury.level I1
```

## 7. Retry And Failed

Each `post` attempt increments `attempt_count`. Retry records keep `last_error`, optional `last_http_status`, and `next_retry_at`. `claim_next()` ignores retry records until `next_retry_at` is due. Once `EVENT_DELIVERY_RETRY_LIMIT` is reached, records become `failed`.

## 8. Idempotency

Memory and SQLite backends keep one effective delivery record per `incident_id`. Re-enqueueing the same incident returns the existing record instead of creating duplicate active delivery records.

## 9. SQLite

SQLite delivery uses `EVENT_DELIVERY_SQLITE_PATH`, persists delivery records across outbox recreation, and stores lock fields for worker leasing. SQLite errors are caught and logged so delivery cannot interrupt realtime detection.

## 10. Security

Delivery payloads and event APIs do not expose local absolute paths, Windows paths, `/workspace`, `logs/event_archive` absolute paths, raw image bytes, secrets, or `lock_token`. Event APIs return `payload_summary` instead of raw `payload_json`.

## 11. Relationship With FallEventReporterService

`FallEventReporterService` remains unchanged and remains the official alert channel. DeliveryOutbox is a controlled, observable side path for future main-system compatibility validation.

## 12. B-Line Frontend Fields

`/events/latest`, `/events/{incident_id}`, and `/events/delivery/*` expose read-only delivery summary fields: `delivery_status`, `delivery_mode`, `dry_run`, `retry_count`, `next_retry_at`, `last_error`, `delivered_at`, and `delivery_backend`.

## 13. Acceptance Commands

Final E2E coverage now includes `tests/test_event_delivery_final_e2e_runbook.py`, which verifies:

- dry-run + SQLite produces `dry_run_sent` and survives outbox recreation.
- mock post receives the main-system payload and marks `sent`.
- mock 500 and retry-limit paths produce `retry` and `failed`.
- `/events/latest` and `/events/{incident_id}` expose only safe delivery summaries.
- legacy reporter defaults and DeliveryOutbox defaults remain unchanged.

Service-level Final integration was also executed with a temporary uvicorn process:

- Port: `8131`
- Incident: `service-final-demo-a`
- Input: `scripts/seed_event_pipeline_demo.py --scenario fall_candidate_support --seed-delivery-dry-run`
- Storage: temporary SQLite EventOutbox and DeliveryOutbox paths
- `/events/status`: event pipeline enabled for the temporary process
- `/events/latest`: returned the seeded event and delivery summary
- `/events/{incident_id}`: returned the seeded event detail
- Delivery summary: `delivery_status=dry_run_sent`, `delivery_mode=dry_run`, `dry_run=true`, `retry_count=0`, `delivery_backend=sqlite`
- Temporary service stopped: yes
- `.env` modified: no
- Real replay executed: no
- Real POST executed: no
- Real VLM executed: no

A/B/C Final E2E delivery guard was executed with a temporary uvicorn process:

- Port: `8134`
- Incident: `abc-final-e2e-a`
- Scenario: `fallen_confirmed_high`
- `/events/status`: enabled for the temporary process
- `/events/latest`: returned the seeded event and delivery summary
- `/events/{incident_id}`: returned event detail
- Delivery summary: `delivery_status=dry_run_sent`, `delivery_mode=dry_run`, `dry_run=true`, `retry_count=0`, `delivery_backend=sqlite`
- B-line delivery fields present: yes
- C-line/VLM disabled did not affect delivery: yes
- Forbidden public fields found: none
- Temporary service stopped: yes
- `.env` modified: no
- Real POST executed: no
- Real VLM/Ollama executed: no

Final freeze conclusion: DeliveryOutbox is frozen as the reliable-delivery side-path stable version. It remains default-off and does not replace `FallEventReporterService`.

Final handover conclusion: the A-line handover pack is sealed in `docs/event_delivery_final_handover_pack.md`, `docs/event_delivery_real_endpoint_activation_runbook.md`, `docs/event_delivery_demo_talking_points.md`, and `docs/event_delivery_change_guard.md`. The marker `DELIVERY_OUTBOX_HANDOVER_PACK_READY` is established. This authorizes demo closure for the reliable-delivery side path only; it does not authorize production endpoint activation.

```powershell
python -m pytest tests/test_event_delivery_payload_compat.py tests/test_event_delivery_outbox.py tests/test_event_delivery_sqlite_outbox.py tests/test_event_delivery_worker.py tests/test_event_delivery_main_system_contract.py -q
python -m pytest tests/test_event_delivery_post_staging.py tests/test_event_delivery_retry_state_machine.py tests/test_event_delivery_idempotency.py tests/test_event_delivery_security_payload.py tests/test_event_delivery_mock_main_system_e2e.py -q
python -m pytest tests/test_event_delivery_final_e2e_runbook.py -q
python -m pytest tests/test_fall_event_reporter_service.py tests/test_fall_alert_polling_api.py -q
python -m pytest tests/test_event_api.py tests/test_event_pipeline_e2e_smoke.py tests/test_event_pipeline_integration.py -q
python -m py_compile app/events/delivery.py app/events/delivery_worker.py app/events/schemas.py app/api/event_api.py app/core/config.py
git diff --check
```

Operational runbooks:

- `docs/event_delivery_final_e2e_runbook.md`
- `docs/event_delivery_real_endpoint_preflight.md`
- `docs/event_delivery_abc_final_integration_ready.md`
- `docs/event_delivery_final_freeze_report.md`

## 14. Not Completed

- Kafka is not integrated.
- Redis is not integrated.
- Celery is not integrated.
- Real VLM remains disabled by default.
- DeliveryOutbox has not replaced the formal main-system alert path.
- Production main-system endpoint activation still requires site configuration and separate acceptance.

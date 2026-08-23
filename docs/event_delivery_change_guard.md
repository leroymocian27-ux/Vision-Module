# Event Delivery Change Guard

## 1. Frozen A-Line Scope

The frozen A-line scope covers:

- `app/events/delivery.py`
- `app/events/delivery_worker.py`
- delivery public summary behavior in `app/api/event_api.py`
- `EVENT_DELIVERY_*` configuration in `app/core/config.py`
- `tests/test_event_delivery_*.py`
- `docs/event_delivery_*.md`

## 2. Allowed Follow-Up Changes

- Documentation supplements.
- Stronger `last_error` redaction.
- Small payload compatibility fixes.
- Staging endpoint configuration notes.
- Retry parameter documentation.
- Focused test hardening.

Allowed changes must preserve default-off behavior and the side-path relationship.

## 3. Forbidden Direct Changes

- Do not enable `EVENT_DELIVERY_ENABLED` by default.
- Do not enable worker delivery by default.
- Do not make `post` the default mode.
- Do not hard-code endpoint URLs or tokens.
- Do not replace `FallEventReporterService`.
- Do not bypass the DeliveryOutbox state machine.
- Do not POST from realtime detection threads.
- Do not expose `target_url`, `lock_token`, `payload_json`, auth headers, tokens, or local absolute paths in public APIs.
- Do not let VLM/Ollama directly trigger delivery.
- Do not add Kafka, Redis, Celery, or a new scheduler without a separate architecture decision.

## 4. Required Regression After Each Change

Run at least:

```powershell
python -m pytest tests/test_event_delivery_abc_final_integration_guard.py -q
python -m pytest tests/test_event_delivery_final_e2e_runbook.py -q
python -m pytest tests/test_event_delivery_payload_compat.py tests/test_event_delivery_outbox.py tests/test_event_delivery_sqlite_outbox.py tests/test_event_delivery_worker.py tests/test_event_delivery_main_system_contract.py -q
python -m pytest tests/test_event_delivery_post_staging.py tests/test_event_delivery_retry_state_machine.py tests/test_event_delivery_idempotency.py tests/test_event_delivery_security_payload.py tests/test_event_delivery_mock_main_system_e2e.py -q
python -m pytest tests/test_fall_event_reporter_service.py tests/test_fall_alert_polling_api.py -q
python -m py_compile app/events/delivery.py app/events/delivery_worker.py app/api/event_api.py app/core/config.py
git diff --check
```

Add `tests/test_event_api.py` when a change touches `/events/latest`, `/events/{incident_id}`, keyframe summary, or public redaction behavior.


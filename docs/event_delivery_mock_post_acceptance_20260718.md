# Event Delivery Mock POST Acceptance

Date: 2026-07-18  
Environment: local development process, temporary SQLite database, loopback-only mock server  
Real main system: not contacted

## Temporary configuration

The acceptance test creates settings in process and does not change `.env`.

```dotenv
EVENT_DELIVERY_ENABLED=true
EVENT_DELIVERY_MODE=post
EVENT_DELIVERY_BACKEND=sqlite
EVENT_DELIVERY_WORKER_ENABLED=true
EVENT_DELIVERY_RETRY_LIMIT=2
EVENT_DELIVERY_RETRY_BACKOFF_SECONDS=30
EVENT_DELIVERY_CLAIM_TTL_SECONDS=15
MAIN_SYSTEM_ALERT_ENABLED=false
MAIN_SYSTEM_ALERT_TIMEOUT_MS=200
EVENT_DELIVERY_TARGET_URL=http://127.0.0.1:<random-port>/<scenario>
```

The mock server uses `ThreadingHTTPServer` bound only to `127.0.0.1` with an
operating-system-assigned port. No configured or discovered main-system address
is used.

## Scenarios and observed behavior

| Scenario | Mock response | Verified record outcome |
| --- | --- | --- |
| Success | `200`, JSON body | `pending -> sending -> sent` |
| Server error | `500` twice | first attempt `retry`; second due attempt `failed` |
| Timeout | server waits 500 ms, client timeout 200 ms | `pending -> sending -> retry`, no HTTP status |
| Invalid response body | `200`, non-JSON body | `pending -> sending -> sent` |

The current delivery contract treats an HTTP 2xx status as success and does not
parse a response body. Therefore the non-JSON 200 response is deliberately
recorded as `sent`; this is an explicit contract boundary, not a claim that a
future formal main-system response schema has been validated.

## Retry, lease, and persistence checks

For the 500 path, the first failure has `attempt_count=1`,
`last_http_status=500`, and a `next_retry_at` approximately 30 seconds in the
future. A worker call before that time claims nothing. The acceptance test then
sets only the temporary test record's retry time to the past and verifies the
second `500` moves it to `failed` at `attempt_count=2`.

At every real loopback HTTP request, the mock server reads the SQLite record.
It observes `delivery_status=sending` and non-empty `lock_owner`, `lock_token`,
and future `lock_until`. Terminal `sent`, `retry`, and `failed` updates clear
the lease fields. This proves lease ownership is persisted before the POST and
released after the outcome is recorded.

## Isolation and legacy alert path

`FallEventReporterService` is unchanged and remains the legacy formal alert
path. It is disabled for this test through `MAIN_SYSTEM_ALERT_ENABLED=false`.
DeliveryOutbox and DeliveryWorker remain optional side paths; a post failure is
stored as `retry` or `failed` and does not throw into realtime detection,
fusion, WebRTC, WebSocket, or REST publishing. Existing realtime-publisher and
event-pipeline regressions are included in the verification run.

## Reproduction

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_event_delivery_mock_post_acceptance.py -q
```

Executed result: `1 passed` (2026-07-18).

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_event_delivery_mock_post_acceptance.py tests\test_event_delivery_mock_main_system_e2e.py tests\test_event_delivery_sqlite_outbox.py tests\test_event_delivery_worker.py tests\test_event_pipeline_e2e_smoke.py tests\test_result_publisher_service.py tests\test_end_to_end_pipeline.py -q
```

Executed combined delivery, event-pipeline, and realtime-publisher regression
result: `61 passed` (2026-07-18). The only warning is FastAPI's upstream
`TestClient` deprecation notice.

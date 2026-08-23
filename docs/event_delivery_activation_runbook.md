# Event Delivery Activation Runbook

## Baseline

Default configuration:

```text
EVENT_DELIVERY_ENABLED=false
EVENT_DELIVERY_MODE=dry_run
EVENT_DELIVERY_BACKEND=memory
EVENT_DELIVERY_WORKER_ENABLED=false
```

With these defaults, DeliveryOutbox does not post to the main system and does not replace `FallEventReporterService`.

## Step 1: Disabled Baseline

Use:

```text
EVENT_DELIVERY_ENABLED=false
EVENT_DELIVERY_WORKER_ENABLED=false
```

Verify:

```powershell
python -m pytest tests/test_fall_event_reporter_service.py tests/test_fall_alert_polling_api.py -q
```

Check:

- `/events/delivery/status` reports `event_delivery_enabled=false`.
- Legacy fall alert polling remains unchanged.

## Step 2: Dry-Run + Memory

Use:

```text
EVENT_DELIVERY_ENABLED=true
EVENT_DELIVERY_MODE=dry_run
EVENT_DELIVERY_BACKEND=memory
EVENT_DELIVERY_WORKER_ENABLED=false
```

Verify:

```powershell
python -m pytest tests/test_event_delivery_outbox.py tests/test_event_delivery_payload_compat.py -q
```

Check:

- Delivery records can be created.
- `delivery_status=dry_run_sent`.
- No HTTP POST occurs.

## Step 3: Dry-Run + SQLite

Use:

```text
EVENT_DELIVERY_ENABLED=true
EVENT_DELIVERY_MODE=dry_run
EVENT_DELIVERY_BACKEND=sqlite
EVENT_DELIVERY_SQLITE_PATH=data/event_delivery_outbox.sqlite3
EVENT_DELIVERY_WORKER_ENABLED=false
```

Verify:

```powershell
python -m pytest tests/test_event_delivery_sqlite_outbox.py -q
```

Check:

- Delivery records survive outbox recreation.
- `for_incident()` returns the same effective record.
- No HTTP POST occurs.

## Step 4: Post + SQLite + Mock Main System

Use:

```text
EVENT_DELIVERY_ENABLED=true
EVENT_DELIVERY_MODE=post
EVENT_DELIVERY_BACKEND=sqlite
EVENT_DELIVERY_WORKER_ENABLED=true
EVENT_DELIVERY_TARGET_URL=<mock-main-system-url>
```

Verify:

```powershell
python -m pytest tests/test_event_delivery_mock_main_system_e2e.py tests/test_event_delivery_worker.py -q
```

Check:

- 2xx moves records to `sent`.
- 500 and timeout move records to `retry`, then `failed` after the retry limit.
- `/events/delivery/status` shows counts.

## Step 5: Post + SQLite + Test Main System

Only run after the target URL, auth expectations, and rollback owner are confirmed.

Observe:

- `pending_count`
- `retry_count`
- `failed_count`
- `last_http_status`
- `last_error`

## Rollback

Set:

```text
EVENT_DELIVERY_ENABLED=false
EVENT_DELIVERY_WORKER_ENABLED=false
```

No code rollback is required for the formal alert path because `FallEventReporterService` remains independent.

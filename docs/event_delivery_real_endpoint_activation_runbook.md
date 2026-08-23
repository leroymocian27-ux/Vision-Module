# Event Delivery Real Endpoint Activation Runbook

## 1. User Confirmation Required Before Access

Do not connect a real endpoint until the user or deployment owner confirms:

- URL.
- HTTP method.
- Auth header name.
- Token source and rotation owner.
- Timeout.
- Retry and backoff policy.
- Idempotency key, preferably `incident_id`.
- Main-system error-code semantics.
- Whether the endpoint accepts `dry_run`.
- Whether the endpoint accepts candidate events.
- Whether the endpoint accepts review-required events.
- Whether the endpoint accepts confirmed events.
- Duplicate alert policy.
- Rollback owner and exact rollback steps.
- Staging canary plan.

No endpoint or token should be written into code or committed documentation.

## 2. Recommended Activation Order

1. Reconfirm the current frozen version.
2. Run dry-run acceptance.
3. Run mock post acceptance.
4. Send one staging endpoint post with one controlled event.
5. Verify staging retry/failed behavior with controlled non-2xx or timeout responses.
6. Run a small staging canary.
7. Ask for manual confirmation from the main-system owner.
8. Decide whether to enter controlled production enablement.

## 3. Temporary Enablement Pattern

Use only session-scoped environment variables for validation:

```powershell
$env:EVENT_DELIVERY_ENABLED="true"
$env:EVENT_DELIVERY_WORKER_ENABLED="true"
$env:EVENT_DELIVERY_MODE="post"
$env:EVENT_DELIVERY_BACKEND="sqlite"
$env:EVENT_DELIVERY_TARGET_URL="<staging-url>"
```

Rules for temporary validation:

- Do not edit local `.env`.
- Record the port, process id, environment values used, and log location.
- Use staging or mock endpoints until production is separately approved.
- Stop the temporary service after verification.
- Clear temporary endpoint and token variables after the run.

## 4. Rollback

Immediate rollback is:

```text
EVENT_DELIVERY_ENABLED=false
EVENT_DELIVERY_WORKER_ENABLED=false
EVENT_DELIVERY_TARGET_URL=
EVENT_DELIVERY_ENDPOINT=
```

Rollback keeps the original `FallEventReporterService` path intact and does not affect realtime detection. Existing DeliveryOutbox records may remain for audit, retry analysis, or manual cleanup.

## 5. Forbidden Actions

- Do not hard-code endpoint URLs or tokens.
- Do not enable `post` by default.
- Do not reuse the legacy reporter URL silently.
- Do not POST from realtime detection threads.
- Do not bypass the DeliveryOutbox state machine.
- Do not replace `FallEventReporterService`.
- Do not production POST without explicit approval.


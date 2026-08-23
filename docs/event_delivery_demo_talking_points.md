# Event Delivery Demo Talking Points

## 1. Correct Statements

- The system keeps the original formal main-system alert path.
- The new `DeliveryOutbox` is an event semantic side path.
- Current delivery is in dry-run or controlled acceptance mode unless explicitly enabled for a mock or staging endpoint.
- `DeliveryOutbox` supports retry, failed records, and idempotency by `incident_id`.
- Side-path delivery failures do not affect realtime detection.
- The public APIs expose safe delivery summaries only.

## 2. Forbidden Statements

- Do not say `DeliveryOutbox` has formally replaced the main-system alert path.
- Do not say the service is already production POSTing to the main system.
- Do not say Kafka, Redis, or Celery are connected.
- Do not say VLM/Ollama directly triggers delivery.
- Do not say delivery failure affects realtime detection.
- Do not reveal target URLs, tokens, lock tokens, raw payloads, or local absolute paths during demos.

## 3. Short Explanations

- `dry_run_sent` means simulated delivery completed; no real POST was sent.
- `sent` means real HTTP `post` succeeded with a 2xx response.
- `retry` means the record is waiting for the next allowed attempt.
- `failed` means the retry limit has been reached.
- `target_url` is hidden by design to avoid leaking internal endpoint information.
- `payload_summary` is intentionally smaller than raw `payload_json` for public API safety.


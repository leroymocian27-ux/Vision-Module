# Qwen VLM Real Endpoint Preflight

## Current State

- `qwen_http` provider shell is reserved and tested with mock transport.
- No real Qwen endpoint is enabled by default.
- `EVENT_VLM_ENDPOINT` defaults to empty.
- `EVENT_VLM_ENABLED=false` means no adapter is created and no network request
  is made.
- No SDK, model download, Kafka, Redis, or Celery integration is part of this
  C-line implementation.

## Required Confirmation Before Real Endpoint Use

The deployment owner must explicitly approve and provide:

- Endpoint URL.
- Network type: internal-only, VPN, private cloud, or external internet.
- Whether image transfer is allowed.
- Required image redaction/de-identification policy.
- Auth header name.
- Token/secret source, such as environment secret manager; never code/docs.
- Timeout budget.
- Maximum concurrency.
- QPS/rate limit.
- Circuit breaker threshold and cooldown.
- Retry policy.
- Log redaction policy.
- Whether `raw_response` may be recorded.
- Where provider diagnostics may be stored.
- Whether local image paths may be stored internally.
- Whether model output may be archived.
- Whether fail-open is mandatory.
- Rollback method and owner.

## Hard Prohibitions

- Do not hardcode endpoint URLs in code.
- Do not put tokens, API keys, or real secrets in code, docs, tests, or
  `.env.example`.
- Do not set `EVENT_VLM_ENABLED=true` by default.
- Do not call VLM from realtime detection, fusion, publishing, WebRTC, WS, REST
  latest-result, or `FallEventReporterService` paths.
- Do not let VLM cancel or downgrade a rule-confirmed fall.
- Do not treat VLM output as medical diagnosis.
- Do not expose local image paths to frontend APIs.
- Do not expose local image paths or image bytes in delivery payloads.
- Do not expose raw provider response in public Event API output.

## Recommended Rollout Order

1. Run default disabled regression.
2. Run `dummy` provider acceptance.
3. Run mock `http` provider acceptance.
4. Run mock `qwen_http` provider acceptance.
5. Run one staging Qwen event with synthetic/non-sensitive evidence.
6. Run a small staging batch.
7. Observe latency, timeout rate, invalid-output rate, queue impact, and memory.
8. Human-review accepted events before controlled enablement.
9. Keep an immediate rollback to `EVENT_VLM_ENABLED=false`.

## Minimum Environment Shape

```dotenv
EVENT_VLM_ENABLED=true
EVENT_VLM_PROVIDER=qwen_http
EVENT_VLM_ENDPOINT=<approved endpoint from deployment secret/config>
EVENT_VLM_TIMEOUT_SECONDS=8
EVENT_VLM_HTTP_HEADERS_JSON=<injected by secret/config if approved>
EVENT_VLM_FAIL_OPEN=true
```

The example above is not a default. It is only a staging/production activation
shape after approval.

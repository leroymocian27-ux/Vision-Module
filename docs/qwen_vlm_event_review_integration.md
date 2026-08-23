# Qwen VLM Event Review Integration

## Position

Qwen or another VLM is reserved as an event-level advisory reviewer:

```text
EvidencePackage + EventSemantics + keyframes + timeline_image
-> qwen_http / http / dummy VLM review
-> VLMReviewResult
-> IntelligentAnalysisEngine rule-first merge
-> TrustedEventResult
```

It does not run in `FallFusionService`, does not participate in realtime first
decision, and does not replace `FallEventReporterService` or
`/integration/fall-alerts/poll`.

## Default Safety

```text
EVENT_VLM_ENABLED=false
EVENT_VLM_PROVIDER=dummy
EVENT_VLM_ENDPOINT=
```

With `EVENT_VLM_ENABLED=false`, no adapter is created and no network request is
made. `dummy` is the safe default provider name only; it is not invoked unless
VLM is explicitly enabled.

## Providers

- `dummy`: deterministic local response for tests and demos; no network.
- `http`: generic future HTTP VLM shell; requires explicit endpoint.
- `qwen_http`: thin Qwen-compatible HTTP shell; no DashScope, Ollama, model SDK,
  or hardcoded endpoint is imported.
- `http_mock`: test transport provider for contract tests.
- `disabled`: compatibility no-op provider.

## Input Contract

`VLMReviewInput` contains:

- `incident_id`
- `camera_id`
- `keyframe_image_paths`
- `timeline_image_path`
- `event_semantics`
- `feature_json`
- `evidence_summary`
- `prompt_version`
- `output_schema_version`

The input is built from event-level evidence and semantics, not from the
realtime detection thread. If both keyframes and timeline image are absent,
HTTP/Qwen review is skipped before any request and the rule result records
`vlm_skipped_no_images`.

## Output Contract

`VLMReviewResult` contains:

- `support_fall_alarm`
- `semantic_event_type`
- `observed_process`
- `adl_likelihood`
- `uncertainty`
- `risk_interpretation`
- `alarm_title`
- `alarm_body`
- `recommended_action`
- `raw_response`
- `parse_error`
- `provider`
- `latency_ms`

Default schema values are:

```text
EVENT_VLM_PROMPT_VERSION=fall_event_review_v1
EVENT_VLM_OUTPUT_SCHEMA_VERSION=vlm_review_result_v1
```

## Prompt And Schema Guard

The prompt requires JSON-only output, no Markdown fences, no invented visual
facts, no medical diagnosis, no realtime decision override, and no single-frame
fall confirmation. ADL-like behavior such as sitting, squatting, bending, or
lying down to rest must be expressed through `adl_likelihood`.

Invalid JSON, Markdown-wrapped JSON, wrong schema version, or invalid field
types are treated as invalid VLM output and fall back to RuleAnalyzer. Missing
advisory fields are defaulted and recorded as
`schema_warning_missing_fields:<field,...>`.

## Merge Policy

- RuleAnalyzer always runs first.
- Confirmed falls stay confirmed and high/critical even when VLM disagrees.
- VLM disagreement is advisory and recorded in uncertainty/degradation.
- Candidate + low ADL + VLM support may enrich explanation/action.
- Candidate + high ADL remains review/unsupported; VLM cannot confirm it alone.
- Unsupported/review rule results cannot be upgraded to confirmed by VLM alone.
- Timeout, invalid JSON/schema, provider error, or skipped-no-image still produce
  `TrustedEventResult` from rules.

## Timeline Image

Timeline image uses six fixed cells: `T-3s`, `T-1s`, `T0`, `T+1s`, `T+3s`,
`T+5s`. Each cell can show offset, frame sequence, fall state, bbox summary, and
missing reason. Missing frames render as placeholders. Archive summaries expose
relative `timeline/timeline.jpg`, never absolute local paths.

## Demo Acceptance

Use `scripts/seed_event_pipeline_demo.py` scenarios:

- `fall_candidate_support`
- `fallen_confirmed_high`
- `adl_suppressed_review`
- `missing_keyframes`
- `vlm_timeout_fallback`
- `vlm_invalid_json_fallback`

The seed script is dev/demo only, does not POST to the main system, and does not
enable a real VLM.

## Final E2E Acceptance

The C-line final E2E suite is documented in
`docs/qwen_vlm_final_e2e_acceptance.md` and covered by
`tests/test_qwen_vlm_final_e2e_acceptance.py`.

It verifies:

- VLM disabled rule-only behavior.
- Dummy provider advisory merge.
- Mock `http` JSON success.
- Mock `qwen_http` JSON success through the same HTTP shell.
- Timeout, invalid JSON, schema error, and no-image fallback.
- Confirmed fall cannot be downgraded by VLM disagreement.
- Candidate + low ADL can be enriched but not confirmed by VLM alone.
- Candidate + high ADL remains review/unsupported.
- Public Event API does not expose local absolute paths or `raw_response`.

`qwen_http` remains a mock/staging-ready provider shell only. A real Qwen
endpoint is still not connected, not enabled by default, and must pass
`docs/qwen_vlm_real_endpoint_preflight.md` before use.

## External Qwen HTTP Vs Local Qwen Ollama

- `qwen_http` is a generic future HTTP endpoint shell. It remains endpoint-based
  and is not enabled by default. It is not the currently recommended route for
  P14 because external Qwen/DashScope integration remains out of scope.
- `qwen_ollama` is the recommended first local experiment path. It calls a
  local Ollama `/api/chat` endpoint only when explicitly enabled.
- The current `qwen_ollama` stage is text-only: no image, no keyframe path, no
  timeline image path, no encoded image data, and no local absolute path is sent
  to the model.
- The local model recommendation is `qwen-vision-cn:latest`, with
  `qwen3.5:9b` as comparison/fallback. Even for vision-capable models, this
  stage sends structured JSON only.

Detailed local integration notes are in
`docs/ollama_qwen_event_review_integration.md`.

P14 evaluation uses `scripts/evaluate_ollama_advisory_review.py` to compare
small local samples, latency, parse success, fail-open behavior, local path
leaks, and advisory-only policy compliance. The default recommendation remains
`KEEP_DISABLED` until a local run meets the gates in
`docs/ollama_qwen_advisory_evaluation_report.md`.

## Production Readiness Checklist

- Approve the Qwen endpoint and network route.
- Configure `EVENT_VLM_ENDPOINT` only in deployment-specific env.
- Keep a short timeout and fail-open behavior.
- Review privacy policy for archived keyframes and timeline images.
- Validate payload logging does not include image bytes or local absolute paths.
- Load-test worker latency and outbox retry behavior.
- Keep `FallFusionService`, `FallEventReporterService`, WebRTC, WS, REST, Kafka,
  Redis, and Celery outside this change.

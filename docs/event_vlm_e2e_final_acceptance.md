# Event VLM E2E Final Acceptance

## Completed C-Line Capabilities

- Event-level VLM review contract: `VLMReviewInput` and `VLMReviewResult`.
- Provider shell: disabled, dummy, http_mock, http, and qwen_http provider.
- Prompt constraints: JSON-only, no invented facts, no medical diagnosis, advisory only.
- Rule-first analysis engine with optional VLM enrichment.
- Failure fallback for timeout, invalid JSON/schema, and generic provider failure.
- Timeline image generation for archived keyframe evidence.
- Dev/demo-only seed script for reproducible frontend/event API checks.
- E2E smoke tests for synthetic candidate/confirmed events.

## VLMReviewInput

- `incident_id`: event id.
- `camera_id`: source camera id.
- `keyframe_image_paths`: archived relative keyframe paths.
- `timeline_image_path`: optional archived timeline image path.
- `event_semantics`: structured semantic JSON.
- `feature_json`: detector/fusion feature summary.
- `evidence_summary`: keyframe and score summary.
- `prompt_version`: prompt contract version.
- `output_schema_version`: expected result schema.

## VLMReviewResult

- `support_fall_alarm`: advisory support flag, never authoritative.
- `semantic_event_type`: advisory event type.
- `observed_process`: visible process summary.
- `adl_likelihood`: low, medium, high, or unknown.
- `uncertainty`: advisory uncertainty list.
- `risk_interpretation`: advisory explanation.
- `alarm_title`, `alarm_body`, `recommended_action`: display text.
- `raw_response`, `parse_error`: provider diagnostics.
- `provider`: disabled, dummy, http_mock, http, or qwen_http.
- `latency_ms`: provider latency when available.

Missing advisory fields fall back to defaults and are recorded in
`parse_error` as `schema_warning_missing_fields:<field,...>`. Invalid JSON,
wrong schema versions, invalid enum values, and Markdown-wrapped JSON still
fall back to `RuleAnalyzer`.

## Provider Configuration

Defaults remain safe:

```text
EVENT_PIPELINE_ENABLED=false
EVENT_VLM_ENABLED=false
EVENT_VLM_PROVIDER=dummy
EVENT_VLM_ENDPOINT=
EVENT_DELIVERY_ENABLED=false
```

`dummy` is deterministic and for tests/demo. `http_mock` is for mock transport
tests. `http` and `qwen_http` are reserved HTTP provider shells and require
explicit enablement and endpoint configuration.

## Rule And VLM Merge Matrix

| Rule result | VLM advisory | ADL | Final policy |
| --- | --- | --- | --- |
| confirmed | any | any | Keep confirmed; never downgrade to low. |
| confirmed | not support | any | Keep confirmed and add disagreement uncertainty. |
| candidate | support | low | Keep rule-supported candidate and enrich text. |
| candidate | support | high | Add uncertainty/review context; do not confirm. |
| candidate | not support | high | Review/unsupported according to rules. |
| review/unsupported | support | low | Advisory only; do not confirm. |
| any | timeout/invalid/failed | any | Use rule result and append degradation. |

## Failure Fallback

- Timeout: `vlm_timeout`.
- Invalid JSON, wrong schema, invalid enum, or Markdown-wrapped JSON: `vlm_invalid_json`.
- Missing images before HTTP/Qwen request: `vlm_skipped_no_images`.
- Network/provider/other exception: `vlm_failed`.

In all cases, `TrustedEventResult` is still generated from `RuleAnalyzer`.

## Timeline Image

Timeline image uses fixed order:

```text
T-3s, T-1s, T0, T+1s, T+3s, T+5s
```

Each cell includes label, offset, frame sequence, fall state, and bbox summary
when available. Missing frames render as placeholders with missing reason.
Archive summary exposes only relative `timeline/timeline.jpg`.

## Demo Seed

`scripts/seed_event_pipeline_demo.py` is dev/demo only and supports:

- `fall_candidate_support`
- `fallen_confirmed_high`
- `adl_suppressed_review`
- `missing_keyframes`
- `vlm_timeout_fallback`
- `vlm_invalid_json_fallback`

It does not send main-system POST requests and does not auto-enable pipeline or VLM flags.

## Acceptance Commands

```powershell
python -m pytest tests/test_vlm_adapter_contract.py tests/test_vlm_http_adapter.py tests/test_vlm_adapter_config.py tests/test_intelligent_analysis_engine_vlm_fallback.py -q
python -m pytest tests/test_timeline_image.py tests/test_demo_seed_event_pipeline.py tests/test_event_pipeline_e2e_smoke.py -q
$files = Get-ChildItem -Path tests -Filter 'test_event_*.py' | ForEach-Object { $_.FullName }
python -m pytest $files -q
python -m py_compile app/events/vlm.py app/events/vlm_adapter.py app/events/vlm_prompt.py app/events/analysis_engine.py app/events/timeline_image.py scripts/seed_event_pipeline_demo.py
git diff --check
```

## A/B/C Boundaries

- A line can consume trusted event fields and delivery-compatible payload fields.
- B line can display VLM advisory fields, uncertainty, degradation, keyframes, and timeline image.
- C line does not modify `FallFusionService`, realtime result publishing, WebRTC, overlay, or `FallEventReporterService`.

## Remaining Non-Goals

- Real VLM is not enabled by default.
- Kafka, Redis, and Celery are not connected.
- Production real provider needs separate load, timeout, privacy, and security validation.
- Medical diagnosis is outside system responsibility.

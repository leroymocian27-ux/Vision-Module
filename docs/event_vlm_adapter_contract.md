# Event VLM Adapter Contract

## Position

The VLM adapter runs after `EvidencePackage` and `EventSemantics` are built. It is an optional advisory review layer for explanation, uncertainty, and recommended action text.

It is not the realtime fall detector, does not replace `FallFusionService`, and does not replace `FallEventReporterService`.

## Configuration

Defaults remain off:

```text
EVENT_VLM_ENABLED=false
EVENT_VLM_PROVIDER=dummy
EVENT_VLM_ENDPOINT=
EVENT_VLM_TIMEOUT_SECONDS=8.0
EVENT_VLM_PROMPT_VERSION=fall_event_review_v1
EVENT_VLM_OUTPUT_SCHEMA_VERSION=vlm_review_result_v1
```

Providers:

- `disabled`: no VLM call.
- `dummy`: deterministic contract-test response.
- `http_mock`: mock HTTP/transport contract tests.
- `http`: reserved interface for a future service; no real model is required.
- `qwen_http`: thin Qwen-compatible HTTP shell; no SDK, model download, or
  hardcoded endpoint is introduced.
- `ollama`: local Ollama text-only HTTP shell.
- `qwen_ollama`: local Qwen-on-Ollama text-only advisory shell.

`EVENT_VLM_ENDPOINT` is accepted as the HTTP endpoint setting. The legacy
`EVENT_VLM_HTTP_MOCK_URL` name is still accepted for tests.

The provider construction entry point is `build_vlm_adapter_from_config(settings)`.
It returns `None` when `EVENT_VLM_ENABLED=false`, a no-op adapter when provider
is `disabled`, and explicit dummy/http/qwen adapters only when enabled by config.
With VLM disabled, the default `dummy` provider name does not create an adapter
and does not make any network request.

Final provider behavior:

| Provider | Network by default | Intended use |
| --- | --- | --- |
| `dummy` | No | Local contract/demo advisory result. |
| `http` | No, unless enabled with endpoint | Generic future HTTP VLM service. |
| `qwen_http` | No, unless enabled with endpoint | Qwen-compatible HTTP endpoint shell. |
| `http_mock` | No real network when transport is injected | Tests only. |
| `ollama` | No, unless explicitly enabled | Local structured JSON review through Ollama. |
| `qwen_ollama` | No, unless explicitly enabled | Local Qwen model through Ollama, text-only. |

## Input

`VLMReviewInput`:

- `incident_id`
- `camera_id`
- `keyframe_image_paths`
- `timeline_image_path`
- `event_semantics`
- `feature_json`
- `evidence_summary`
- `prompt_version`
- `output_schema_version`

## Output

`VLMReviewResult`:

- `support_fall_alarm`: `true`, `false`, or `null`
- `semantic_event_type`
- `observed_process`
- `adl_likelihood`: `low`, `medium`, `high`, or `unknown`
- `uncertainty`
- `risk_interpretation`
- `alarm_title`
- `alarm_body`
- `recommended_action`
- `raw_response`
- `parse_error`
- `provider`
- `latency_ms`

## Prompt Constraints

The prompt template is in `app/events/vlm_prompt.py`. It requires JSON-only output, forbids invented visual facts and medical diagnosis, and states that VLM is advisory only.

Forbidden output:

- Markdown fences around JSON.
- Medical diagnosis.
- Claims about facts not visible in keyframes or structured evidence.
- Decisions to call emergency services.
- Instructions that override `FallFusionService` or `RuleAnalyzer`.

Long advisory text is truncated by the adapter for display safety:

- `alarm_title`: 80 characters.
- `alarm_body`: 300 characters.
- `recommended_action`: 220 characters.
- `risk_interpretation`: 500 characters.

Missing advisory fields may fall back to empty/default values and are recorded
in `parse_error` as `schema_warning_missing_fields:<field,...>`. Invalid enum
values, wrong schema versions, malformed JSON, or Markdown-wrapped JSON are
treated as invalid VLM output.

## HTTP Request/Response Shape

The `http` and `qwen_http` providers send `VLMReviewInput` as JSON. If
`EVENT_VLM_ENDPOINT` is empty, no request is made and the engine records
`vlm_failed`. If both `timeline_image_path` and `keyframe_image_paths` are
absent, the adapter skips before request and the engine records
`vlm_skipped_no_images`.

The `ollama` and `qwen_ollama` providers send a text-only `/api/chat` payload
to `EVENT_VLM_OLLAMA_ENDPOINT`. That payload excludes images, encoded image
data, `keyframe_image_paths`, `timeline_image_path`, `image_path`,
`snapshot_url`, and local absolute paths. It includes structured event
semantics, numeric feature summary, keyframe count, missing-frame count,
`prompt_version`, and `output_schema_version`.

A valid response is a JSON object matching `VLMReviewResult`:

```json
{
  "schema_version": "vlm_review_result_v1",
  "support_fall_alarm": true,
  "semantic_event_type": "fall_candidate",
  "observed_process": "person moves from standing to low posture",
  "adl_likelihood": "low",
  "uncertainty": [],
  "risk_interpretation": "consistent with fall-like motion",
  "alarm_title": "Possible fall review",
  "alarm_body": "Review keyframes and live stream.",
  "recommended_action": "Check the live stream and confirm onsite."
}
```

`timeline_image_path` is optional. When present it points to the archived
timeline image. When absent, providers should use `keyframe_image_paths`.

## Fallback

`IntelligentAnalysisEngine` runs `RuleAnalyzer` first. VLM failures return the rule result and add:

- `vlm_timeout`
- `vlm_invalid_json`
- `vlm_skipped_no_images`
- `vlm_failed`

For local Ollama, connection refused or unavailable maps to `vlm_failed`,
timeout maps to `vlm_timeout`, and invalid JSON/schema maps to
`vlm_invalid_json`.

Confirmed falls are never cancelled by VLM. A confirmed fall with VLM
non-support records `vlm_disagree` while keeping the rule result. Candidate
events may receive advisory explanation/action enrichment, but VLM does not
change the original `fall_state` or directly confirm unsupported events.

Successful advisory fields may be copied to `TrustedEventResult` as read-only
summary fields: `vlm_provider`, `vlm_latency_ms`, `observed_process`,
`risk_interpretation`, and `adl_likelihood`. `raw_response` stays internal and
is not exposed through public Event API payloads.

Field adoption boundary:

- Adoptable: `observed_process`, `risk_interpretation`, `alarm_title`,
  `alarm_body`, `recommended_action`, `uncertainty`.
- Advisory only: `support_fall_alarm`, `semantic_event_type`, `adl_likelihood`.
- Never directly overwritten by VLM: rule final decision, confirmed fall risk,
  delivery status, realtime fall state.

## Current Limits

Real VLM, Kafka, Redis, Celery, and model downloads are not introduced. `dummy`,
`http_mock`, and `qwen_http` are for interface validation and future integration
only until deployment explicitly configures an approved endpoint.

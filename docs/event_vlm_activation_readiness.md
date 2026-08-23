# Real VLM Activation Readiness Assessment

Status: not approved for a real VLM provider  
Date: 2026-07-18  
External image/data transfer: prohibited until the gates below are approved

## C-Line Freeze Marker

P14 is complete and frozen under `VLM_OLLAMA_ADVISORY_FREEZE_READY`.

Current VLM/Ollama status: `KEEP_DISABLED`. Rule review remains the default
event-level semantic review path. Ollama/Qwen is retained only as optional
advisory-only reserved capacity and must not be enabled for staging or default
demo use without a fresh passing text-only evaluation.

## Decision

Do not enable a real provider in the current environment. The current event
pipeline is safe by default because:

```dotenv
EVENT_VLM_ENABLED=false
EVENT_VLM_PROVIDER=dummy
EVENT_VLM_ENDPOINT=
EVENT_VLM_TIMEOUT_SECONDS=8.0
```

The adapter is an event-worker side path, after evidence and semantics have
already been created. It is not in capture, detection, tracking, fusion,
WebRTC, WebSocket, REST latest-result publishing, or the legacy alert path.

## Local Ollama Direction

The approved direction for a future controlled Qwen experiment is **local
Ollama first**, not an external hosted VLM. The local machine inventory checked
on 2026-07-18 contains these vision-capable models:

| Model | Capability observed | P13 role |
| --- | --- | --- |
| `qwen-vision-cn:latest` | completion, vision, tools, thinking; local Chinese visual-analysis system prompt | Preferred first model for advisory-only event review. |
| `qwen3.5:9b` | completion, vision, tools, thinking | Backup comparison model only after the preferred model passes the same gates. |

The local Ollama service is reachable through the local CLI and no model was
loaded during this readiness review. This is inventory verification only: no
event, keyframe, image, or external provider request was sent.

The execution order is deliberately unchanged: complete P8 delivery auth, P9
post-event evidence completion, P10 confirmed-event acceptance, P11 real-camera
stability, and P12 production readiness checks before beginning P13. Locality
removes external network transfer from the first experiment, but it does not
make the model authoritative or remove the need for privacy, retention, access,
resource, and audit controls.

P13 now uses `qwen_ollama` as the controlled local provider. The old
`ollama_qwen` name remains a compatibility alias. The `qwen_http` shell is a
separate endpoint-based provider and is not the recommended first local trial.

## Current Adapter Audit

| Mode | Actual behavior | Appropriate use | Real-provider status |
| --- | --- | --- | --- |
| `disabled` | When `EVENT_VLM_ENABLED=false`, no adapter is constructed. When explicitly enabled with provider `disabled`, adapter returns no result. | Default production-safe posture. | Safe, no VLM traffic. |
| `dummy` | Builds event input and returns deterministic local advisory output. No HTTP call. | Contract and UI tests. | Not a model. |
| `http_mock` | Sends `VLMReviewInput` JSON to an explicitly configured HTTP endpoint or injected transport. Validates response JSON/schema. | Local mock contract tests only. | Not a security approval. |
| `http` | Uses the same HTTP implementation as `http_mock`, with a caller-supplied endpoint. | Reserved provider shell. | Not approved for external or production use. |
| `qwen_ollama` | Loopback-only Ollama `/api/chat` adapter; structured semantics only, `stream=false`, JSON advisory output. | Local controlled P13 experiment. | Default disabled; real images remain unadmitted. |

The HTTP adapter uses `requests.post(..., json=VLMReviewInput,
timeout=EVENT_VLM_TIMEOUT_SECONDS)`. It treats timeout, request errors,
malformed JSON, schema mismatches, and invalid enum values as advisory failure.
The rule result is returned with `vlm_timeout`, `vlm_invalid_json`, or
`vlm_failed` degradation markers.

## Existing Safety Properties

- `RuleAnalyzer` executes before optional VLM analysis.
- `fallen_confirmed` remains rule-confirmed, critical, and supported even when
  VLM returns `support_fall_alarm=false`.
- VLM cannot directly rewrite `final_event_type`, `final_risk_level`,
  `support_fall_alarm`, delivery state, or realtime fall state.
- Current code only enriches selected display-oriented text and uncertainty.
- HTTP response content must parse as `vlm_review_result_v1`; malformed output
  falls back to rules.
- The event worker, rather than the realtime publisher, invokes the analysis
  engine. A slow VLM can delay event review, but it must not block realtime
  capture, fusion, WebRTC, WS, or REST result output.

## Current Gaps That Block Real Enablement

1. **No approved media contract.** `VLMReviewInput` carries relative archived
   `keyframe_image_paths` and optional `timeline_image_path`, not image bytes.
   A remote provider cannot safely resolve those local paths. Adding image
   upload, signed retrieval, shared storage, or a provider SDK requires a
   separate privacy and security design.
2. **No external endpoint allowlist or provider authentication implementation.**
   `EVENT_VLM_ENDPOINT` is a free-form URL and current HTTP calls do not add
   provider credentials or enforce HTTPS/host allowlists.
3. **No privacy transformation.** The input includes `incident_id`, `camera_id`,
   structured event semantics, bbox sequence, and feature data. There is no
   de-identification policy, consent registry, face/body redaction pipeline,
   retention policy, or outbound audit trail.
4. **No concurrency governor.** Calls are synchronous within the event worker.
   There is no provider queue bound, in-flight semaphore, circuit breaker,
   budget counter, or overload shedding policy.
5. **No cost accounting.** The system does not record request units, image
   counts, token usage, provider pricing version, or per-camera/event budgets.
6. **No formal real-provider response acknowledgement contract.** The adapter
   validates the JSON shape but there is no supplier SLA, model/version pin,
   audit retention, or evaluation acceptance threshold.
7. **No completed local-Ollama provider configuration.** There is no stable
   `EVENT_VLM_MODEL`, no loopback-only endpoint validation, no explicit
   image-send switch, and no tested conversion between the event schema and the
   Ollama chat/generate request/response format.

## Required Admission Gates

All gates must pass before changing `EVENT_VLM_PROVIDER=http` for an approved
external endpoint. `ollama_qwen` remains a separate local-only experiment.

### JSON-Only Output

- Provider must return one JSON object, no Markdown fences or prose.
- Response must validate strictly against a versioned schema. Unknown or absent
  advisory fields must follow an agreed compatibility rule.
- Schema requires `schema_version=vlm_review_result_v1` or a deliberately
  versioned successor with migration tests.
- Invalid JSON, wrong schema, invalid enum, HTTP error, and timeout must always
  keep the rule result and emit a degradation reason.

### Timeout, Availability, and Concurrency

- Establish a provider-specific deadline, initially no greater than the current
  event-worker budget. Timeout is advisory failure, never an event failure.
- Implement a bounded queue and a per-provider in-flight semaphore. Initial
  canary recommendation is one in-flight request per process until measured
  event throughput and provider latency support a higher limit.
- Add a circuit breaker: repeated timeout/error events stop outbound VLM calls
  for a cooldown and mark subsequent events with a local degradation reason.
- Record latency percentile, timeout count, queue depth, dropped advisory work,
  and circuit state. No unbounded backlog is permitted.

### Privacy and Data Governance

- Written approval must identify the provider, processing region, data
  controller, retention period, deletion process, subprocessors, and incident
  contact.
- Do not transmit an image, keyframe path resolvable by the provider, face,
  body, name, camera identifier, or stable incident identifier to an unapproved
  external service.
- Before any remote image transfer, implement and validate the approved media
  policy: minimum necessary frames, face/person de-identification where
  required, camera/incident pseudonyms, TLS, scoped credentials, and outbound
  audit records without raw images or secrets.
- Local `dummy` and local loopback `http_mock` tests are permitted only with
  synthetic/non-sensitive test data.

### Cost and Capacity

- Obtain the model's input/output pricing, image pricing, rate limits, and
  minimum billing terms in writing.
- Estimate daily and monthly cost from: eligible incidents per camera, cameras,
  selected keyframes per incident, average input/output units, retries, and a
  20 percent incident-volume contingency.
- Define hard daily/monthly budget caps and an automatic policy: when the cap is
  reached, skip VLM and keep the normal rule-only result with `vlm_budget_skip`.
- Record provider model ID/version, request count, image count, estimated cost,
  and budget remaining for each advisory call.

## Advisory-Only Field Contract

The following fields are proposed for the next version of VLM advisory data.
They are not yet a production wire contract and must be stored separately from
the authoritative `TrustedEventResult` decision fields.

| Proposed advisory field | Intended meaning | Allowed source / restriction |
| --- | --- | --- |
| `scene_summary` | Concise visual description of posture, movement, and visible context. | Derived from current event evidence only; must state uncertainty when frames are missing. Maps conceptually from current `observed_process`. |
| `possible_false_positive_reason` | Plausible non-fall explanation such as sitting, bending, occlusion, or poor view. | Advisory hypothesis only. Must never cancel a rule-confirmed fall. Relates to `adl_likelihood` and current uncertainty. |
| `care_advice` | Non-diagnostic operational advice, such as inspect live view or ask onsite staff to check. | No medical diagnosis, triage claim, or emergency instruction. Maps conceptually from `recommended_action`. |
| `confidence_explanation` | Explanation of evidence quality and uncertainty, not an authoritative probability. | Must distinguish rule evidence from VLM interpretation. Maps conceptually from `risk_interpretation`. |

These fields may enrich the event review panel and archived semantic record only.
They must not modify:

```text
fall_state
final_event_type
final_risk_level
support_fall_alarm
DeliveryRecord status
FallFusionService output
WebRTC / WS / REST realtime result
```

For a rule `fallen_confirmed`, a disagreement may add
`possible_false_positive_reason` and `vlm_disagree` for reviewer context, but
the confirmed event remains confirmed and the existing alarm contract remains
unchanged.

## Future Validation Sequence

1. Complete P8-P12 first; do not use VLM work to bypass delivery, evidence, or
   real-camera acceptance gaps.
2. Keep `disabled`; run the current adapter and fallback test suite.
3. Implement a local-Ollama-only provider with a fixed model selector. The first
   candidate is `qwen-vision-cn:latest`; bind only to a loopback endpoint and
   reject non-loopback endpoints in the local experiment mode.
4. Validate JSON schema and timeout behavior with dummy/local mocks and
   synthetic data only. The first local-Qwen pass must send structured semantics
   only: no image bytes, local paths, or archive URLs.
5. Add an explicit, default-false image-send switch only after the local image
   policy, minimal-frame policy, local retention, and audit controls are tested.
6. Complete privacy, concurrency, circuit-breaker, telemetry, and cost/resource
   gates. Local GPU/CPU memory and queue limits replace external billing as the
   first capacity budget, but must still be measured and bounded.
7. Run a local advisory-only canary with human review and immediate disable
   controls. External providers remain out of scope unless separately approved.
8. Promote only after quality, safety, privacy, and operational acceptance are
   signed off. VLM remains advisory at every stage.

## Verification

The following tests prove current adapter behavior only; they do not approve a
real model or external service:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_vlm_adapter_config.py tests\test_vlm_adapter_contract.py tests\test_vlm_http_adapter.py tests\test_intelligent_analysis_engine.py tests\test_intelligent_analysis_engine_vlm_fallback.py -q
```

Required current outcomes:

- disabled configuration makes no provider call;
- dummy and local HTTP/mock paths validate contract behavior;
- timeout/invalid output fall back to rules;
- VLM disagreement cannot downgrade `fallen_confirmed`.

## P13 Local Ollama Text-Only Trial Status

The local provider shell now supports `ollama` and `qwen_ollama` as explicit,
default-disabled providers. Recommended local settings are:

```dotenv
EVENT_VLM_PROVIDER=qwen_ollama
EVENT_VLM_OLLAMA_ENDPOINT=http://127.0.0.1:11434/api/chat
EVENT_VLM_OLLAMA_MODEL=qwen-vision-cn:latest
EVENT_VLM_OLLAMA_FALLBACK_MODEL=qwen3.5:9b
EVENT_VLM_OLLAMA_TEXT_ONLY=true
EVENT_VLM_OLLAMA_INCLUDE_IMAGES=false
```

The trial sends structured event JSON only. It does not send images, keyframe
paths, timeline image paths, local absolute paths, encoded image data, tokens,
endpoints, raw payloads, or lock tokens to the model. It remains advisory-only
and cannot change confirmed-fall status, risk level, fall state, delivery
status, or realtime outputs.

## P14 Local Ollama Evaluation Status

P14 adds `scripts/evaluate_ollama_advisory_review.py` for small-sample local
Ollama/Qwen advisory evaluation. The script is effectively dry-run unless
`--allow-local-ollama` is supplied, and it rejects non-loopback endpoints.

Current status:

| Item | Status |
| --- | --- |
| Default enabled | No. `EVENT_VLM_ENABLED=false` remains unchanged. |
| Demo-only allowed | Not recommended from the latest smoke; both local model candidates timed out at the 15 second budget. |
| Staging ready | No. P14 smoke timed out for both `qwen-vision-cn:latest` and `qwen3.5:9b`, and sample size is not sufficient for staging. |
| Image input | Not enabled. |
| External Qwen endpoint | Not enabled and not the recommended current path. |

Recommended P14 posture is `KEEP_DISABLED`. `ALLOW_DEMO_ONLY` should be
reconsidered only after at least five local text-only samples meet the parse,
latency, privacy, and advisory-only gates documented in
`docs/ollama_qwen_advisory_evaluation_report.md`.

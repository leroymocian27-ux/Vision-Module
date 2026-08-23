# Local Ollama Qwen Event Review Integration

## Freeze Status

Freeze marker: `VLM_OLLAMA_ADVISORY_FREEZE_READY`.

Current recommendation: `KEEP_DISABLED`. The default review path is
`RuleAnalyzer`; Ollama/Qwen remains only a reserved advisory-only enrichment
capability. It is not enabled by default and does not participate in realtime
first decision, fall confirmation, risk-level assignment, or delivery state.

## Position

Local Ollama/Qwen review is an event-level advisory experiment. It runs after
`EventSemantics` and rule analysis, then returns a `VLMReviewResult` that may
enrich explanation, advice, uncertainty, and read-only advisory fields.

It does not run in capture, detection, tracking, `FallFusionService`,
`ResultPublisherService`, WebRTC, WS, REST realtime output, or
`FallEventReporterService`.

## Text-Only First Stage

The first stage sends structured JSON only. It does not send images, image
bytes, encoded image data, local paths, keyframe image paths, or timeline image
paths. Vision-capable models may be selected, but they receive no image input.

Preferred local model:

- `qwen-vision-cn:latest`

Fallback/comparison model:

- `qwen3.5:9b`

## Configuration

Defaults remain safe:

```dotenv
EVENT_VLM_ENABLED=false
EVENT_VLM_PROVIDER=dummy
EVENT_VLM_OLLAMA_ENDPOINT=http://127.0.0.1:11434/api/chat
EVENT_VLM_OLLAMA_MODEL=qwen-vision-cn:latest
EVENT_VLM_OLLAMA_FALLBACK_MODEL=qwen3.5:9b
EVENT_VLM_OLLAMA_TIMEOUT_SECONDS=15
EVENT_VLM_OLLAMA_TEXT_ONLY=true
EVENT_VLM_OLLAMA_INCLUDE_IMAGES=false
```

Ollama is called only when `EVENT_VLM_ENABLED=true` and
`EVENT_VLM_PROVIDER=ollama` or `EVENT_VLM_PROVIDER=qwen_ollama`.

## Payload Contract

Allowed input:

- `incident_id`
- `camera_id`
- event type / fall state / risk level / confidence from structured semantics
- `EventSemantics` actor, scene, motion, posture, evidence, risk, uncertainty,
  and degradation fields after path-key filtering
- numeric feature summary
- keyframe count and missing-frame count
- `prompt_version`
- `output_schema_version`

Forbidden input:

- `keyframe_image_paths`
- `timeline_image_path`
- `image_path`
- `snapshot_url`
- local absolute paths
- image bytes or encoded image data
- endpoint, token, auth headers, raw payloads, or lock tokens

## Prompt Constraints

The Ollama prompt states that the model receives structured JSON only, not
images. It must not claim to have seen frames, must not invent people or scene
details, must not provide medical diagnosis, and must return JSON only. It may
only provide advisory fields such as `observed_process`,
`risk_interpretation`, `adl_likelihood`, `uncertainty`, `alarm_title`,
`alarm_body`, and `recommended_action`.

## Merge Policy

- `RuleAnalyzer` runs first.
- Ollama cannot change `fall_state`, `final_event_type`, `final_risk_level`,
  `support_fall_alarm`, delivery state, or confirmed-fall status.
- Candidate events may receive advisory explanation and action enrichment.
- Confirmed falls remain confirmed even if Ollama disagrees.
- High ADL likelihood adds uncertainty and does not confirm a fall.

## Fallback

- Timeout -> `vlm_timeout`
- Unavailable / connection refused / endpoint failure -> `vlm_failed`
- Invalid JSON or schema violation -> `vlm_invalid_json`

`TrustedEventResult` is still generated from rules in all failure modes.

## Local Smoke

Optional local smoke may check `GET http://127.0.0.1:11434/api/tags`. If Ollama
is unavailable, do not install models or download anything. Mock tests remain
the acceptance source. If a local call is made, it must use temporary
environment variables, send structured JSON only, avoid main-system POST, and
leave `.env` unchanged.

Observed local check on 2026-07-18:

- `/api/tags` was reachable on `127.0.0.1:11434`.
- Models listed: `qwen-vision-cn:latest`, `qwen3.5:9b`.
- One text-only structured event smoke attempted `qwen-vision-cn:latest`.
- The model call timed out at the configured 15 second budget.
- `TrustedEventResult` still generated from rules with `vlm_timeout`.
- No images, local paths, external endpoint, or main-system POST were used.

P14 controlled smoke on 2026-07-18:

| Model | Cases | Parse success | Timeout count | Average latency | Status |
| --- | ---: | ---: | ---: | ---: | --- |
| `qwen-vision-cn:latest` | 1 | 0 | 1 | 15034.416 ms | `KEEP_DISABLED` |
| `qwen3.5:9b` | 1 | 0 | 1 | 15031.970 ms | `KEEP_DISABLED` |

Both calls used only `http://127.0.0.1:11434/api/chat`, sent structured JSON
only, and failed open to the rule result. The timeout pattern means local
Ollama should remain disabled for default and staging paths.

## P14 Evaluation Flow

P14 adds a local evaluation script for small-sample latency and policy checks:

```powershell
python scripts/evaluate_ollama_advisory_review.py --max-cases 6
```

The script is effectively dry-run by default. It calls real local Ollama only
when `--allow-local-ollama` is present and `--dry-run` is not present. The
endpoint must be loopback, for example:

```powershell
python scripts/evaluate_ollama_advisory_review.py `
  --allow-local-ollama `
  --endpoint http://127.0.0.1:11434/api/chat `
  --model qwen-vision-cn:latest `
  --timeout 15 `
  --max-cases 2
```

The evaluation covers `fall_candidate_support`, `fallen_confirmed_high`,
`adl_suppressed_review`, `missing_keyframes`, `vlm_timeout_fallback`, and
`vlm_invalid_json_fallback`. It writes only local report files under
`tmp_qwen_ollama_eval/` unless overridden. It does not write event outbox
records, does not start the service, does not POST to the main system, and does
not modify `.env`.

## P14 Enablement Gate

For demo consideration, require:

- at least 5 structured event samples;
- parse success at or above 80 percent;
- average latency no more than 8 seconds;
- single-call latency no more than 15 seconds;
- zero local path leaks;
- zero policy violations;
- rule-confirmed events are not downgraded;
- candidates are not confirmed by Ollama alone;
- timeout and invalid JSON fail open.

If samples are insufficient or timeout is observed, the report must return
`KEEP_DISABLED` or `ALLOW_DEMO_ONLY`, never `READY_FOR_STAGING`.

## Production Limits

This is not production enablement. Before any image-based phase, a separate
privacy, retention, de-identification, latency, resource, and human-review
acceptance process is required.

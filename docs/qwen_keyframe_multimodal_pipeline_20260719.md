# Local Qwen Keyframe Multimodal Pipeline

Date: 2026-07-19  
Status: `CODE_READY_NOT_RUNTIME_VERIFIED`  
Scope: Vision Service event sidecar only. Robot, Go2 SDK/DDS, RobotAssistTask, and robot control are out of scope for this pipeline.

## Purpose

The existing realtime chain remains responsible for detection and fall decisions. This change adds an optional local-Qwen sidecar that describes archived event keyframes after a `fallen_confirmed` event.

```text
RTSP / replay
-> Capture / Detection / Tracking / Pose / Temporal
-> FallFusionService (authoritative)
-> realtime WebRTC / WS / REST

fallen_confirmed event sidecar
-> evidence keyframes archived
-> QwenKeyframeWorker (one background worker)
-> localhost Ollama vision model
-> structured advisory
-> qwen_advisory.json + /events/{incident_id} + review panel
```

The Qwen result is advisory-only. It cannot change `fallen_candidate`, `fallen_confirmed`, risk level, Delivery state, `FallFusionService`, or the existing `FallEventReporterService`.

## Scope Reset

The Vision delivery plan is now focused on the video and multimodal event chain:

- In scope: keyframes, local Qwen image description, structured advisory, archive, API, frontend review, failure degradation, and later real-video acceptance.
- Frozen for this Vision scope: Go2 SDK, DDS, robot physical state, robot control, RobotAssistTask dispatch, and robot UI integration.
- Historical robot Mock/contract artifacts are retained. They are not deleted and are not a prerequisite for this feature.

## Security and Privacy Boundary

- The only accepted analysis endpoint is `http://localhost:11434` or `http://127.0.0.1:11434` (including `/api/chat`).
- The request contains image bytes encoded for Ollama's `messages[].images` field. It never contains image paths, archive paths, API URLs, RTSP URLs, tokens, `incident_id`, `track_id`, `camera_id`, names, or stable identity fields.
- The persisted advisory contains structured descriptions only. It contains no raw Ollama response or request payload.
- `QWEN_MEDIA_INPUT_ENABLED=true` and `QWEN_MEDIA_PRIVACY_APPROVED=true` are both required before image analysis can start.
- The feature is default-off. The actual `.env` was not changed by this implementation.
- Images are never sent to an external model endpoint.

## Runtime Contract

The archived per-event output file is:

```text
{EVENT_ARCHIVE_DIR}/{safe-camera-id}/{safe-incident-id}/qwen_advisory.json
```

The public API never returns this local path. It returns the object as `qwen_advisory` in `/events/latest`, `/events/{incident_id}`, and `/events/outbox` after path redaction.

Example payload:

```json
{
  "schema_version": "qwen_keyframe_advisory.v1",
  "analysis_status": "completed",
  "provider": "ollama_qwen",
  "model_name": "qwen-vision-cn:latest",
  "image_count": 6,
  "analyzed_offsets_ms": [-3000, -1000, 0, 1000, 3000, 5000],
  "scene_summary": "人员处于低姿态。",
  "posture_description": "疑似侧卧。",
  "movement_description": "画面内运动较少。",
  "possible_false_positive_reasons": ["局部遮挡"],
  "care_advice": ["建议工作人员复核现场。"],
  "confidence_explanation": "依据多个事件时间槽的可见姿态。",
  "advisory_confidence": "medium"
}
```

No `incident_id`, keyframe file name, local directory, URL, RTSP address, token, or raw model output belongs in this file.

## Processing Policy

1. The default trigger is `fallen_confirmed` only. `fallen_candidate` image processing requires explicit `EVENT_QWEN_KEYFRAME_ANALYZE_CANDIDATES=true`.
2. The event archive is written before Qwen is scheduled.
3. If post-event keyframe collection is enabled, Qwen waits until its collection window closes so it can use the best available T+ frames.
4. A single-concurrency `QwenKeyframeWorker` handles one event at a time outside capture, inference, publisher, WebRTC, WebSocket, and REST threads.
5. A duplicate event cannot schedule a second active/completed analysis for the same `incident_id`.
6. Missing frames are reported as `missing_reasons`; they are never replaced with fabricated images.

Status mapping:

```text
disabled    feature off
pending     queued after archive
processing  local worker is reading archive-owned images / calling Ollama
completed   validated structured result was archived
degraded    no usable images, timeout, invalid JSON, or local model unavailable
failed      unexpected worker failure
```

On `degraded` or `failed`, the existing rule result remains available. No event retry, Delivery retry, or realtime result is changed by Qwen failure.

## Feature Flags

All defaults remain safe in `.env.example`:

```text
EVENT_QWEN_KEYFRAME_ANALYSIS_ENABLED=false
EVENT_QWEN_KEYFRAME_ANALYZE_CANDIDATES=false
EVENT_QWEN_KEYFRAME_ENDPOINT=http://127.0.0.1:11434/api/chat
EVENT_QWEN_KEYFRAME_MODEL=qwen-vision-cn:latest
EVENT_QWEN_KEYFRAME_TIMEOUT_SECONDS=90
EVENT_QWEN_KEYFRAME_MAX_IMAGES=6
EVENT_QWEN_KEYFRAME_MAX_IMAGE_BYTES=5242880
QWEN_MEDIA_INPUT_ENABLED=false
QWEN_MEDIA_PRIVACY_APPROVED=false
```

The startup safety gate rejects enabled keyframe analysis unless pipeline archive, JSON archive, keyframe archive, local endpoint, local media input, and privacy approval are all present.

For a future approved local acceptance run, use session-only environment variables, not a persisted `.env` edit:

```powershell
$env:EVENT_PIPELINE_ENABLED="true"
$env:EVENT_RING_BUFFER_ENABLED="true"
$env:EVENT_WORKER_ENABLED="true"
$env:EVENT_SEMANTIC_ENABLED="true"
$env:EVENT_ARCHIVE_ENABLED="true"
$env:EVENT_ARCHIVE_SAVE_KEYFRAMES="true"
$env:EVENT_ARCHIVE_SAVE_JSON="true"
$env:EVENT_QWEN_KEYFRAME_ANALYSIS_ENABLED="true"
$env:QWEN_MEDIA_INPUT_ENABLED="true"
$env:QWEN_MEDIA_PRIVACY_APPROVED="true"
$env:EVENT_DELIVERY_ENABLED="false"
$env:EVENT_VLM_ENABLED="false"
$env:MAIN_SYSTEM_ALERT_ENABLED="false"
```

Before that run, verify that the selected local model is image-capable. `qwen3.5:9b` must not be used as the image model unless its installed variant demonstrably accepts Ollama image messages.

## Implemented Files

- `app/events/qwen_keyframe.py`: localhost-only payload, JSON-only result contract, forbidden-metadata validation.
- `app/events/qwen_keyframe_worker.py`: single-concurrency asynchronous worker and safe failure mapping.
- `app/events/archive.py`: archive-owned image-byte reader and `qwen_advisory.json` writer.
- `app/events/schemas.py` and `app/events/outbox.py`: persistent advisory state.
- `app/events/pipeline.py`: scheduling after archive / post-frame completion.
- `app/api/event_api.py`: public status exposure through the existing redaction boundary.
- `frontend_demo/index.html` and `frontend_demo/app.js`: advisory status, scene, posture/movement, advice, and uncertainty display.

## Verification Performed

```text
tests/test_qwen_keyframe_multimodal.py: 6 passed
Focused event/privacy/config regression: 33 passed
Python py_compile: PASS
frontend_demo/app.js node --check: PASS
git diff --check: PASS
```

Automated tests use a local injected transport. A separate controlled local smoke was run with one synthetic geometric image and `qwen-vision-cn:latest`; it did not use camera data, event data, paths, RTSP, or an external endpoint. No service was started/restarted, actual `.env` was not modified, and no main-system POST was sent.

A broader repository run produced `629 passed, 9 failed`. The Qwen/event-related privacy failure was corrected in this change. The remaining eight failures are outside this feature and are in pre-existing pose production-preflight, fall-hint label-progress, and pose-optimization expectations whose configured model/data baselines do not match their historical assertions. They are not treated as multimodal acceptance evidence.

## Remaining Acceptance

`CODE_READY_NOT_RUNTIME_VERIFIED` remains the event-pipeline status. The local model smoke has passed, but the integrated event worker has not yet processed a real or authorized replay keyframe. Before claiming multimodal event acceptance PASS, run an approved synthetic or authorized replay event and record:

- actual model name and Ollama endpoint (`localhost` only);
- image count, latency, valid/invalid JSON result, and fallback status;
- `qwen_advisory.json` existence and public API redaction;
- WebRTC, WS, REST, and `FallFusionService` continuity;
- explicit evidence type: synthetic, authorized replay, or real camera.

Do not call this production-ready or real-camera verified until the appropriate source and runtime acceptance are complete.

# Local Qwen Keyframe Multimodal Smoke

Date: 2026-07-19  
Result: `PASS` for local synthetic-image adapter smoke only.

## Environment

```text
Ollama endpoint: http://127.0.0.1:11434/api/chat
Model: qwen-vision-cn:latest
Architecture: qwen35
Parameters: 9.7B
Capabilities reported by Ollama: completion, vision, tools, thinking
```

The endpoint was local loopback. No external endpoint was used.

## Input Boundary

The smoke submitted exactly one program-generated 160x96 synthetic image containing a neutral geometric shape. It did not submit:

```text
camera frame
real person image
RTSP URL
file path
archive path
keyframe URL
incident_id
track_id
camera_id
name or identity data
token
```

## Result

```text
model_name: qwen-vision-cn:latest
analysis_status: completed
latency_ms: 10565.179
schema_version: qwen_keyframe_advisory.v1
JSON contract: valid
image_input: local_ollama_only
external_endpoint: NOT_USED
```

The response contained a scene summary, posture description, movement description, possible false-positive reasons, confidence explanation, and `advisory_confidence=low`. The synthetic image intentionally has no real scene semantics, so descriptive quality was not evaluated as a fall-detection benchmark.

## Compatibility Fix Applied

The initial cold attempt timed out at 60 seconds. A later warm attempt returned JSON that echoed the requested output schema rather than returning the result object directly, so it was correctly rejected by the strict parser. The adapter now:

- sends an Ollama native JSON Schema in `format`;
- requests `think=false`;
- instructs the model not to echo its request;
- rejects unexpected fields, paths, URLs, identifiers, and raw response storage.

After this change, the local smoke passed. The image-worker default timeout is 90 seconds to tolerate a 9.7B local vision-model cold start without affecting the realtime path.

## What This Does Not Prove

```text
not a real camera acceptance
not an authorized replay acceptance
not a real fallen_confirmed algorithm acceptance
not six-keyframe event acceptance
not a production privacy approval
not a production activation
```

The actual `.env` remains unchanged and `EVENT_QWEN_KEYFRAME_ANALYSIS_ENABLED` remains default-off. A future approved event-pipeline run must use session-only settings and record the full event, archive, API, frontend, WebRTC, WS, and REST evidence.

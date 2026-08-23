# Qwen Real-Event Stability Acceptance Plan

Date: 2026-07-19  
Objective: prove the local Qwen keyframe sidecar is stable for a real algorithm event without changing `FallFusionService`, production `.env`, real main-system POST, or the realtime video chain.

## Current Starting Point

```text
Qwen adapter and worker: CODE_READY
Local qwen-vision-cn:latest synthetic-image smoke: PASS
Candidate -> confirmed requeue: PASS in automated regression
Real/authorized replay fallen_confirmed: NOT_RUN
Real RTSP Qwen event: NOT_RUN
```

The local model is 9.7B and image-capable. Its warm synthetic-image smoke completed in about 10.6 seconds. The keyframe worker is single-concurrency and outside realtime processing. Its default timeout is 90 seconds to tolerate cold model load.

## Gate 0: Source and Authorization

One source must be selected before any runtime work:

| Preferred order | Acceptable source | Result label |
| --- | --- | --- |
| 1 | Authorized real fall replay with traceable origin | `VERIFIED_AUTHORIZED_REPLAY` |
| 2 | Authorized real RTSP camera and a naturally observed/approved test fall event | `VERIFIED_REAL` |
| 3 | Synthetic event/video | `VERIFIED_SYNTHETIC`, preparation only |

Current local MP4 files under `logs/` and `tests/fixtures/` are not automatically authorized real sources. They must not be used to claim a real or authorized-replay result without an owner confirming provenance and permission.

Required operator approvals:

```text
1. Authorization to process the selected source's event keyframes locally.
2. Authorization to start an isolated temporary Vision instance, or a controlled 8000 restart window.
3. Confirmation that no real main-system POST or alert should occur.
```

## Gate 1: Isolated Runtime Preflight

Prefer a temporary loopback instance such as `127.0.0.1:8135`; do not disturb the currently running 8000 instance. Use an isolated event SQLite database and archive directory. Set variables only in that PowerShell session:

```powershell
$env:EVENT_PIPELINE_ENABLED="true"
$env:EVENT_RING_BUFFER_ENABLED="true"
$env:EVENT_WORKER_ENABLED="true"
$env:EVENT_SEMANTIC_ENABLED="true"
$env:EVENT_ARCHIVE_ENABLED="true"
$env:EVENT_ARCHIVE_SAVE_KEYFRAMES="true"
$env:EVENT_ARCHIVE_SAVE_JSON="true"
$env:EVENT_KEYFRAME_SERVING_ENABLED="true"
$env:EVENT_QWEN_KEYFRAME_ANALYSIS_ENABLED="true"
$env:EVENT_QWEN_KEYFRAME_MODEL="qwen-vision-cn:latest"
$env:EVENT_QWEN_KEYFRAME_TIMEOUT_SECONDS="90"
$env:QWEN_MEDIA_INPUT_ENABLED="true"
$env:QWEN_MEDIA_PRIVACY_APPROVED="true"

$env:EVENT_DELIVERY_ENABLED="false"
$env:EVENT_VLM_ENABLED="false"
$env:MAIN_SYSTEM_ALERT_ENABLED="false"
```

Before running a source, require:

```text
/healthz = 200
/events/status reports event pipeline and Qwen keyframe analysis enabled
Ollama endpoint is loopback only
event delivery disabled
text VLM disabled
main-system alert disabled
```

## Gate 2: Confirmed Event Acceptance

1. Start the approved replay or RTSP source without changing Fusion thresholds.
2. Observe a real algorithm `fallen_candidate -> fallen_confirmed` transition for one track.
3. Record the resulting `incident_id`.
4. Confirm the same incident is requeued after its upgrade; this is required so Qwen analyzes confirmed evidence rather than only the earlier candidate.
5. Confirm the advisory lifecycle:

```text
pending -> processing -> completed
```

`degraded` is an acceptable diagnostic result, not a PASS. `failed` requires investigation before retry.

## Gate 3: Evidence, API and UI Checks

For the confirmed incident, verify:

```text
qwen_advisory.json exists in the controlled archive
/events/{incident_id} has qwen_advisory.analysis_status=completed
image_count > 0
scene_summary is non-empty
no Qwen result field exposes paths, URLs, RTSP, tokens, incident_id, track_id, or camera_id
/demo/ displays Qwen status, scene, posture/movement, care advice and uncertainty
WebRTC stays connected
WebSocket stays connected
REST status remains fresh
```

Run the read-only verifier after the event:

```powershell
python scripts\check_qwen_keyframe_event_acceptance.py `
  --base-url http://127.0.0.1:8135 `
  --incident-id <confirmed-incident-id> `
  --require-six-keyframes `
  --output docs\qwen_real_event_acceptance_check_YYYYMMDD.json
```

The verifier accepts loopback URLs only and does not start services, write configuration, contact Ollama, or read archive paths.

## Gate 4: Stability Run

After one successful confirmed event, repeat with at least three independent confirmed events from the approved source. Record:

```text
event-to-qwen-completed latency
Qwen image count and missing reasons
valid JSON rate
completed/degraded/failed count
Qwen queue depth
capture/detect/publish FPS
frame_age_ms
WebRTC/WS disconnect count
CPU, GPU/VRAM and memory
archive growth
```

Then run 30 minutes with the sidecar enabled. The acceptance condition is no material regression compared with the same source's realtime baseline, no uncontrolled queue growth, no privacy leak, and no effect on Fusion outputs.

## Pass / Revise / Blocked Rules

```text
PASS
  authorized replay or real source
  real algorithm fallen_confirmed
  Qwen completed for each accepted event
  structured result and archive file exist
  API/UI work with no sensitive leakage
  realtime chain has no material regression

REVISE
  Qwen timeout, invalid JSON, queue backlog, incomplete evidence, or measurable realtime regression

BLOCKED
  no authorized source, no privacy approval, no restart/start authorization, unavailable Ollama, or an unsafe endpoint
```

## Rollback

1. Stop the temporary instance.
2. Close the PowerShell session to remove temporary flags.
3. Keep the original 8000 process untouched and confirm `/healthz` remains healthy.
4. Preserve the controlled acceptance archive for review; do not copy it into a production archive.

## Deliverable

Create `docs/qwen_real_event_stability_acceptance_YYYYMMDD.md` containing source classification, authorization reference, model, incident IDs, timing, Qwen states, keyframe completeness, API/UI evidence, realtime metrics, console results, rollback confirmation, and a final `PASS / REVISE / BLOCKED` decision.

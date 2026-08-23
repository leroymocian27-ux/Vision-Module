# Real Camera Stability Acceptance (P11-R)

Date: 2026-07-18  
Machine environment: local Windows development workstation, `camera-service`  
Target duration: 30-60 minutes per round  
Result: NOT_RUN

## P11-R Result Summary

```yaml
rtsp_source_available: NO
sensitive_url_redacted: YES
actual_env_modified: NO
delivery_enabled: false
vlm_enabled: false
main_system_alert_enabled: false
realtime_chain_stability_gate: NOT_RUN
event_sidecar_stability_gate: NOT_RUN
production_ready: NO
```

The user did not provide an accessible, approved, and safely recordable real
RTSP source. P11-R therefore did not connect to a camera, start the service,
or run Round A or Round B. Mock camera mode exists in the local environment but
was not used because it cannot substitute for real RTSP acceptance.

## Preconditions Check

The current runtime device configuration was inspected without printing any
credential or RTSP URL. Its camera status is `not_found`, camera IP is empty,
and `rtsp_url` is empty. No default RTSP configuration was present. The
available default source is mock-camera mode, which is not an acceptable
substitute for this real-camera acceptance.

No RTSP connection precheck was attempted because no approved source exists.
No RTSP connection, server, worker, or browser session was started for P11-R.
No actual `.env` file was modified.

## Required Rounds

### Round A: Realtime Baseline

```dotenv
EVENT_PIPELINE_ENABLED=false
EVENT_DELIVERY_ENABLED=false
EVENT_VLM_ENABLED=false
MAIN_SYSTEM_ALERT_ENABLED=false
```

Status: NOT_RUN. Running time: 0 minutes. A credential-approved real RTSP
source was unavailable. WebRTC, WebSocket, REST/status, FPS, frame age,
latency, CPU/GPU/memory, browser console, screenshots, and process-cleanup
metrics were not collected because no service was started.

### Round B: Event Sidecar

```dotenv
EVENT_PIPELINE_ENABLED=true
EVENT_RING_BUFFER_ENABLED=true
EVENT_WORKER_ENABLED=true
EVENT_SEMANTIC_ENABLED=true
EVENT_DELIVERY_ENABLED=false
EVENT_VLM_ENABLED=false
MAIN_SYSTEM_ALERT_ENABLED=false
```

Status: NOT_RUN. Running time: 0 minutes. This configuration must be supplied
as process-local overrides or an approved deployment configuration, not by
editing `.env` during the run. EventOutbox/SQLite/archive growth, event-worker
errors, post-event keyframe collection, and impact on WebRTC/WS/REST were not
observed because Round B was not started.

## Event and Evidence Result

```yaml
fallen_candidate: NO
fallen_confirmed: NO
incident_id: null
archive_summary_evidence_status: NOT_RUN
sqlite_growth: NOT_RUN
archive_growth: NOT_RUN
console_warn_error: NOT_RUN
screenshot_paths: []
```

No event result is implied by this `NOT_RUN` record. In particular, no replay,
synthetic input, or mock camera result was relabeled as a real-camera event.

## Metrics To Record During The Actual Run

For each round, collect the following over 30-60 minutes:

- WebRTC connection continuity and decoded video state.
- WebSocket message continuity and result timestamp freshness.
- `/status` health, `frame_age_ms`, capture/detect/publish FPS, and latency.
- `camera_lost`, `capture_stale`, `inference_slow`, reconnect, and console errors.
- SQLite event outbox counts, archive growth, cleanup logs, CPU, GPU, and memory.
- Redacted screenshot paths for WebRTC, `/demo/`, status, and event review.

## Safety Controls

Delivery, real VLM/Ollama, and main-system alerts remain disabled for both
rounds. The RTSP URL must be recorded only as a redacted identifier such as
`rtsp://<camera-host>:<port>/<profile>`; usernames, passwords, tokens, and
query strings must not enter the report.

## Conclusion

- realtime_chain_stability_gate: NOT_RUN
- event_sidecar_stability_gate: NOT_RUN

To execute P11, provide an approved reachable RTSP source through the existing
device configuration or approved deployment mechanism, then run both rounds for
the target duration with the listed metrics and screenshots. Do not use a mock
camera or prior replay evidence to claim this gate.

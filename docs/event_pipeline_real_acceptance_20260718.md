# Event Pipeline Real Acceptance - 2026-07-18

## Scope And Safety Boundary

This is a local development acceptance run against a real FastAPI service and
a local replay file. It is not a physical-camera or production-main-system
acceptance.

The temporary `127.0.0.1:8013` process received these environment overrides
only for its own lifetime:

```text
EVENT_PIPELINE_ENABLED=true
EVENT_RING_BUFFER_ENABLED=true
EVENT_WORKER_ENABLED=true
EVENT_SEMANTIC_ENABLED=true
EVENT_ARCHIVE_ENABLED=true
EVENT_OUTBOX_BACKEND=sqlite
EVENT_OUTBOX_SQLITE_PATH=data/event_outbox_real_acceptance_20260718.sqlite3
EVENT_ARCHIVE_DIR=logs/event_archive/real_acceptance_20260718

EVENT_DELIVERY_ENABLED=false
EVENT_DELIVERY_WORKER_ENABLED=false
EVENT_VLM_ENABLED=false
EVENT_VLM_PROVIDER=disabled
MAIN_SYSTEM_ALERT_ENABLED=false
MAIN_SYSTEM_REPORT_DRY_RUN=true
```

No change was made to `.env`. No main-system POST or VLM call was enabled.

## Video Source

- Source type: local fall replay, not a live physical-camera fall.
- Source path: `D:\Program\vision_service\logs\acceptance\cropped_recording_2026-06-20T07-32-20-181Z\run2\cropped_recording_run2.mp4`
- OpenCV probe: opened successfully, 150 frames, 2.0 FPS, 644x360.
- Historical replay documentation records this file as a confirmed-fall replay.
  Under the current runtime profile this acceptance run produced candidate
  events, not `fallen_confirmed`; no thresholds or decision logic were changed
  to force a confirmation.

## Event Result

The primary inspected archived incident was:

```text
incident_id: vision-fall-camera_01-track-2-20260718012327-0004
event_type: fall_candidate
fall_state: fallen_candidate
event risk level: high
trusted result risk level: medium
outbox status: delivery_pending
```

The event worker produced `EvidencePackage`, `EventSemantics`, and
`TrustedEventResult`. `/events/status` reported the event pipeline, ring
buffer, semantic worker, and SQLite outbox as enabled/running. It reported
six completed event records and zero pending, processing, reviewed, or failed
records at the end of the run.

## Endpoint Verification

| Surface | Result |
| --- | --- |
| `GET /events/status` | 200; pipeline/ring/worker/semantic enabled, VLM disabled, SQLite outbox, worker running. |
| `GET /events/latest?camera_id=camera_01` | 200; returned the inspected incident and its event/semantic/archive summary. |
| `GET /events/{incident_id}` | 200; returned full event lifecycle, evidence, semantics, trusted result, archive summary, and no delivery record. |
| `GET /integration/results/camera_01/latest` | 200 during replay; frame 26 reported `fallen_candidate`, `risk_level=medium`, and `detector.result_source=fusion_slot`. |
| WebSocket `/ws/results?camera_id=camera_01` | Connected; a replay message at frame 26 contained `fallen_candidate` and `fusion_slot`. |
| WebRTC through `/demo/` | Connected; browser video reached ready state 4 at 644x360 and WebSocket was connected. |

## Keyframes And Degradation

The event API returned all six fixed timeline entries:

| Offset | Keyframe URL / state | HTTP result |
| --- | --- | --- |
| T-3s | `t_minus_3s` available | `200 image/jpeg` |
| T-1s | `t_minus_1s` available | `200 image/jpeg` |
| T0 | `t0` available | `200 image/jpeg` |
| T+1s | `no_frame_near_target` | no URL issued |
| T+3s | `no_frame_near_target` | no URL issued |
| T+5s | `no_frame_near_target` | no URL issued |

Archive summary: `3 saved / 3 missing`, with JSON files and timeline image
under `logs/event_archive/real_acceptance_20260718/camera_01/<incident_id>/`.

The post-trigger frame degradation is expected from the current asynchronous
worker behavior: it processes an event immediately after trigger time, so
future T+1s/T+3s/T+5s frames may not yet be present in the ring buffer. This
is a known P1 finding, not a hidden success condition. A later improvement can
defer evidence finalization until the configured post-event window has elapsed.

## Frontend Verification

- Page: `http://127.0.0.1:8013/demo/?v=real-acceptance-20260718`
- Screenshot: `tmp_event_visual_qa/event_pipeline_real_acceptance_20260718.png`
- The Event Semantic Review panel displayed the incident, candidate state,
  risk, confidence, delivery status, archive state, rule explanation,
  recommended action, degradation reasons, six timeline cards, and three
  loaded keyframe images.
- Browser diagnostics: no console errors; no failed keyframe image loads.
- Existing video and overlay DOM nodes remained present.

## Main-Chain Impact

No regression was observed in the realtime output surfaces during this run:

- REST continued to publish the candidate result from the fused slot.
- WebSocket continued to emit realtime messages.
- WebRTC connected and decoded the replay video.
- Delivery, VLM, and legacy main-system alert posting stayed disabled.

## Acceptance Conclusion

P1 is accepted for the local replay candidate-event path: realtime result to
SQLite outbox, event semantics, archive, event APIs, and frontend review all
worked together without observed impact on REST, WebSocket, or WebRTC.

This is not a `fallen_confirmed` acceptance and not a real-camera acceptance.
The three missing future keyframes should be addressed before claiming a full
six-image post-event evidence package in production.

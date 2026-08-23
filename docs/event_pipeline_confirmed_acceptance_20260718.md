# Confirmed Event Pipeline Acceptance

Date: 2026-07-18

## Source

Source type: synthetic `VisionResult`, not replay and not a physical-camera
algorithm confirmation. It carries `fall_state=fallen_confirmed`, critical risk,
and high fall evidence solely to exercise the event-sidecar contract.

## Result

The generated incident ID is created dynamically by `IncidentManager` during
the test. The synthetic record completed these verified states:

- event `fall_state=fallen_confirmed`;
- trusted result `final_event_type=fallen_confirmed`, critical risk, and
  `support_fall_alarm=true`;
- `/events/latest` and `/events/{incident_id}` returned HTTP 200;
- detail contained evidence, semantics, trusted result, and archive summary;
- DeliveryOutbox was disabled, VLM/Ollama was disabled, and
  `MAIN_SYSTEM_ALERT_ENABLED=false`.

Three pre/trigger keyframes were available in the synthetic ring buffer. The
three future slots correctly remained missing because P9 collection was not
enabled for this acceptance. Keyframe serving was disabled, so no keyframe URL
or local absolute path was exposed.

## Surface Scope

The synthetic acceptance proves the confirmed **event pipeline** from realtime
result object through archive and event APIs. Existing realtime publisher and
WebSocket behavior are covered by regression tests, but no separate browser
session was opened for this synthetic run. Frontend screenshot: `NOT_RUN`.

## Conclusion

- confirmed event pipeline acceptance: REVISE (synthetic event/archive/API core passed; runtime REST/WS/demo evidence is still required)
- real algorithm confirmed acceptance: NOT_RUN

This must not be represented as a real replay/physical-camera model-confirmed
fall acceptance. A later P10 replay or camera run must capture REST latest,
WebSocket, and `/demo/` screenshot evidence for an organically produced
confirmed result.

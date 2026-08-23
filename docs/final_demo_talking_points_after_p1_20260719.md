# Final Demo And Defense Talking Points After P1

## Three-Minute Version

"The realtime authority remains the existing capture, detection, tracking,
temporal and `FallFusionService` chain. WebRTC, WebSocket and REST publish that
realtime result independently of event semantics."

"The event sidecar is feature-flagged. When enabled for a controlled demo, it
turns a candidate into an incident, evidence timeline, rule-first explanation,
archive and controlled delivery record without blocking the realtime decision."

"Today’s P1 used a local synthetic candidate and a clearly marked synthetic
confirmed comparison. Both show six keyframes and rule review. Delivery is
dry-run, so no real main-system alert was sent. Local Ollama remains disabled
because it is advisory-only and has not passed its readiness gate."

## Eight-Minute Outline

1. Show the realtime path on `8000`; state that `FallFusionService` is the
   authority and event pipeline is disabled on that instance.
2. Show the temporary local event review; identify the source as synthetic.
3. Select the candidate manually from Recent Events, not Latest.
4. Explain T-3 through T+5 evidence, rule explanation, degradation reporting
   and safe relative keyframe API URLs.
5. Explain `dry_run_sent`: delivery mechanics verified, zero real POST.
6. Show VLM disabled/rule fallback and explain advisory-only policy.
7. State retained `FallEventReporterService` boundary and no replacement claim.
8. Finish with the authorized roadmap: P2 restart approval, P3-P5 real source,
   then staging/canary contract work.

## Expected Questions

| Question | Standard answer |
| --- | --- |
| Did the model decide the fall? | No. `FallFusionService` remains the realtime decision authority. |
| Is synthetic confirmed a real confirmed event? | No. It is a local comparison record for UI/data-path validation only. |
| Was an alert sent to the main system? | No. `dry_run_sent` does not make an HTTP POST. |
| Why is Ollama disabled? | The local advisory smoke did not meet latency/JSON reliability gates. It is never the first decision path. |
| Why retain the old reporter? | DeliveryOutbox is an additive evidence/delivery sidecar. `FallEventReporterService` remains the legacy formal alert implementation. |
| Why not enable production POST now? | Endpoint, authentication, acknowledgement, idempotency and canary approvals are not yet supplied. |

## Statements To Avoid

- Do not say the system has production alerting, real-camera stability proof or
  real algorithm-confirmed six-frame proof.
- Do not say a VLM improves fall accuracy, receives images, or performs medical
  diagnosis.
- Do not expose RTSP values, tokens, target URLs, raw payloads, lock tokens or
  local paths.
- Do not claim Kafka, Redis or Celery are connected.

## Current Route

`P1=PASS` for synthetic formal demonstration. `P2` waits for an approved
restart of `8000`; `P3-P5` wait for an authorized real RTSP/replay; `P6` waits
for staging contract and explicit approval. These are real acceptance gates,
not missing presentation features.

# Phase 5 Acceptance Record

Date: 2026-05-22

## Scope

Phase 5 implements the rule-based Temporal Decision Layer for fall-risk preview.

This phase does not implement GRU/LSTM, formal alarms, main-backend POST, snapshot capture, retry queue, mobile push, or production emergency notification.

The current result should be treated as a local preview and engineering baseline, not as final medical or safety-grade fall detection.

## Completed Capabilities

- Target-level temporal feature extraction from tracking and pose results.
- Per-target feature window for short temporal context.
- Mock sequence probability model based on rule features.
- Fall state machine with the following states:
  - `normal`
  - `unstable`
  - `falling`
  - `fallen_candidate`
  - `fallen_confirmed`
  - `cooldown`
- Local `alarm_preview` payload for frontend display.
- `/status.temporal` visibility.
- `/demo` frontend preview fields:
  - Fall State
  - Risk Level
  - Fall Probability
  - Countdown
- Dataset evaluation scripts and report generation.

## Runtime Modules

- YOLO person detect: provides person bounding boxes.
- Tracking: provides `track_id`, target selection, and target continuity.
- Identity binding: can attach `person_id/person_name` when identity service is available.
- YOLO-Pose: provides 17 keypoints for the tracked target.
- Behavior layer: provides interpretable states such as `standing`, `walking`, `sitting`, `bending`, `lying`, and `unknown`.
- Temporal rule preview: consumes tracking, pose, and behavior output to estimate fall-risk preview state.

Current Phase 5 pipeline:

```text
RTSP
-> CaptureWorker
-> FrameBuffer
-> DetectionWorker
-> TrackingWorker
-> PoseWorker
-> Behavior
-> ResultPublisher
-> TemporalService
-> WebSocket result
-> /demo overlay
```

## Explicitly Not Included

- No GRU.
- No LSTM.
- No learned temporal model training.
- No formal fall alarm.
- No POST to main backend.
- No snapshot saving.
- No retry queue.
- No production notification workflow.

## Dataset Evaluation

Dataset: UR Fall Detection Dataset, locally available subset.

Evaluation size:

- ADL normal videos: 11
- Fall videos: 7

Current Phase 5.8 result:

| Metric | Result |
| --- | --- |
| ADL unstable | `0/11` |
| ADL falling false positive | `0` |
| ADL candidate false positive | `0` |
| ADL confirmed false positive | `0` |
| Fall falling recall | `5/7` |
| Fall candidate recall | `0/7` |
| Fall confirmed recall | `0/7` |

Current missed fall samples:

- `fall-02.mp4`
- `fall-03.mp4`

Artifacts:

- `logs/phase5_dataset_eval/summary.json`
- `logs/phase5_dataset_eval/per_video.jsonl`
- `docs/phase5_dataset_report.md`

## Current Strategy Conclusion

The rule-based preview is intentionally conservative.

It currently suppresses high-level ADL false positives well:

- No ADL sample entered `fallen_candidate`.
- No ADL sample entered `fallen_confirmed`.
- No ADL sample entered `falling` after Phase 5.8 tuning.

However, fall recall is incomplete:

- `5/7` fall samples reached `falling`.
- `0/7` reached `fallen_candidate`.
- `0/7` reached `fallen_confirmed`.

This means the current rule version is suitable as an interpretable preview layer and debugging baseline. It is not suitable as the final formal alarm basis.

## Human Test Plan

Human tests should be safe and controlled. Do not perform a real fall.

Recommended actions:

- Stand still.
- Walk left and right.
- Sit down normally.
- Bend forward.
- Pick up an object.
- Fast crouch.
- Low-posture hold.
- Safe prone/lying simulation on a mat or bed.

## Human Acceptance Criteria

Normal actions:

- Standing, walking, sitting, bending, and picking things up should not enter `fallen_candidate`.
- Standing, walking, sitting, bending, and picking things up should not enter `fallen_confirmed`.

High-risk simulations:

- Fast crouch, imbalance simulation, or safe low-posture transition may enter `unstable` or `falling`.
- `fallen_candidate` is allowed only if there is a clear prior falling-like transition followed by low posture.
- `fallen_confirmed` is not required for this phase.

System stability:

- WebRTC video should remain smooth.
- RTSP stream should remain connected.
- Detection, tracking, pose, behavior, and temporal preview should fail gracefully if any submodule errors.
- Temporal preview should not block the main video path.

## Known Risks

- The public dataset subset is still small.
- The current rules may miss some falls, especially samples where tracking or pose evidence is weak.
- `fall-02.mp4` and `fall-03.mp4` remain missed in the current dataset run.
- The current rule layer is conservative and not optimized for `fallen_candidate` or `fallen_confirmed` recall.
- More real-room and camera-angle variation is needed before using these rules as alarm evidence.

## Next Stage Recommendation

Do not enter GRU/LSTM immediately.

Recommended next steps:

- Expand public dataset coverage if accessible.
- Record controlled human ADL and safe fall-like simulations.
- Continue logging false positives and missed cases.
- Only after normal behavior remains stable and high-level false positives remain controlled should Phase 6 GRU/LSTM be discussed.


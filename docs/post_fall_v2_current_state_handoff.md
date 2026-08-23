# Post-Fall V2 Current State Handoff

Date: 2026-08-13

> Historical / superseded on 2026-08-14.  
> Use [post_fall_v2_current_state.md](post_fall_v2_current_state.md) and `artifacts/post_fall_v2/finalization/` as the current engineering baseline.

## Answers to the final audit questions

**A. Default pipeline:** `post_fall_v2`.

**B. First formal fall-decision AI:** EfficientNet-B0 ONNX binary classifier, emitting `FALL` or `NON_FALL`.

**C. Does NON_FALL call Qwen?** No.

**D. When is FallEvent created?** Immediately when the binary aggregator confirms the fall, before future keyframe collection and before Qwen.

**E. Which frames does Qwen receive?** The event package requests `T-3s`, `T-1s`, `T0`, `T+1s`, `T+3s`, and `T+5s`. Future frames are collected asynchronously; missing or out-of-tolerance frames are explicitly marked degraded.

**F. Is Qwen real?** Yes, in the PFV2 default profile it is the real local `PFV2QwenFallAnalyzer` backed by `QwenKeyframeAnalyzer` and Ollama. The dummy analyzer remains available for unit injection only.

**G. Model name:** `qwen-vision-cn:latest`.

**H. How many Qwen calls for one continuous incident?** One main Qwen analysis call. Incident idempotency and the runtime state machine prevent repeated submissions.

**I. Does Qwen failure remove the alarm?** No. The binary-confirmed `FallEvent` remains confirmed; only `vlm_status` and `vlm_analysis` degrade.

**J. Are Legacy models loaded in PFV2?** Formal Legacy workers are not started. Construction-level tests also verify that Legacy YOLO and Temporal ONNX loaders are not called when PFV2 auxiliary person detection is disabled.

**K. Can the frontend see Qwen?** Yes. The demo exposes PFV2 pipeline, binary label, fall probability, incident ID, keyframe status, VLM status, and the Qwen summary from the realtime result.

**L. What prevents Production Ready?** Target-camera RTSP accuracy and production threshold transfer have not been run or verified. They remain `NOT_RUN` and `NOT_VERIFIED`.

## Configuration

The checked-in default uses local Qwen and future keyframe collection. External delivery and main-system alert POST remain disabled. `PIPELINE_MODE=legacy` remains supported as rollback configuration.

## Test evidence

```text
732 passed, 2 warnings
Real Qwen single-image smoke: PASS
Real Qwen six-image smoke: PASS
Replay Binary -> Future Keyframes -> Real Qwen: PASS
PFV2 FastAPI + /demo safe smoke: PASS
Target camera RTSP: NOT_RUN
Production threshold: NOT_VERIFIED
```

## Operational note

The current binary threshold `0.3979087471961975` is an engineering/default threshold based on current OOF evidence, not a target-camera production calibration. Keep this distinction in demos, reports, and acceptance records.

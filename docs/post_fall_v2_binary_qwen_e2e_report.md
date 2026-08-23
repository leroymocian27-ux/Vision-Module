# Post-Fall V2 Binary -> Real Qwen E2E Report

Date: 2026-08-13

## Final status

`ENGINEERING_COMPLETE`

`PRODUCTION_VALIDATION_BLOCKED`

The local engineering chain is complete and verified. The target camera RTSP source was not available for this run, so production accuracy and threshold transfer remain explicitly unverified.

## Gate results

| Gate | Result | Evidence |
| --- | --- | --- |
| PFV2 binary-first runtime | PASS | `tests/test_post_fall_v2_runtime_service.py`, stream isolation tests |
| NON_FALL does not call Qwen | PASS | PFV2 runtime tests |
| Confirmed fall creates event before VLM | PASS | Runtime keyframe collection tests |
| Future keyframes are real future frames | PASS | `tests/test_post_fall_v2_future_keyframe_collection.py` |
| Duplicate frame rejection and degraded package | PASS | Future keyframe tests |
| Real Qwen single-image smoke | PASS | `scripts/smoke_qwen_keyframe_multimodal.py` |
| Real Qwen six-image smoke | PASS | `scripts/smoke_qwen_keyframe_six_images.py` |
| PFV2 replay with real Qwen | PASS | `artifacts/post_fall_v2/replay_e2e/derived_hold_report_20260813_final.json` |
| Legacy model isolation | PASS | `tests/test_post_fall_v2_no_legacy_model_loading.py` |
| Frontend safe smoke | PASS | FastAPI `/demo/` smoke; PFV2 fields present |
| Full regression | PASS | `732 passed, 2 warnings` |
| Target camera RTSP accuracy | NOT_RUN | No target-camera run in this evidence package |
| Production threshold transfer | NOT_VERIFIED | Current threshold remains engineering/default |

## Real Qwen single-image smoke

- Model: `qwen-vision-cn:latest`
- Provider: local Ollama at `127.0.0.1`
- Images: 1
- Result: PASS
- Measured latency: `8962.88 ms`

## Real Qwen six-image smoke

- Model: `qwen-vision-cn:latest`
- Images: 6
- Result: PASS
- Measured latency: `21992.052 ms`
- Returned PFV2 detail fields: posture, movement level, attempt to stand, persistent ground state, help gesture, visibility, occlusion, scene risks, summary, review points, confidence.

## Replay E2E

Input: `private_test_assets/fall_replay_acceptance_derived_hold.mp4`

- Binary results: `63`
- Confirmed events: `1`
- Incident ID: `pfv2-pfv2_replay-8e01fe15b6d7`
- Binary label: `FALL`
- Fall probability at final result: `0.6489647626876831`
- Keyframe package: `ready`
- Requested offsets: `[-3000, -1000, 0, 1000, 3000, 5000]`
- Resolved offsets: all six
- Qwen status: `completed`
- Qwen model: `qwen-vision-cn:latest`
- Qwen latency: `17473.293 ms`
- Qwen confidence: `0.95`
- Same incident updated: PASS
- Outbox incident IDs: exactly the same incident ID
- Duplicate event count: `0`

The `T+5000` frame was resolved at `+4484 ms` with `516 ms` timing error, within the configured `750 ms` tolerance. The report records the actual timestamp error; it does not label the frame as exact `T+5s`.

## Safety boundary

The final default configuration has `EVENT_DELIVERY_ENABLED=false` and `MAIN_SYSTEM_ALERT_ENABLED=false`. Qwen accepts only local media bytes through a localhost Ollama endpoint. No RTSP URL, local media path, credential, or identity field is sent to Qwen.

## Remaining production gate

Acquire an approved target-camera sample and RTSP endpoint, run the binary threshold transfer/accuracy protocol, and record the result separately. A local replay PASS must not be presented as target-camera production accuracy.

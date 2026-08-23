# Post-Fall V2 Current Camera Domain Evidence Report

Date: 2026-08-11

Phase: `P2.5_CURRENT_CAMERA_DOMAIN_EVIDENCE_COLLECTION`

Execution phase alignment: `P2.5C_TARGET_CAMERA_DATA_ACQUISITION_AND_VALIDATION`

## Executive Status

P2.5 tooling is ready, but current camera domain validation is still blocked.

The project environment can run the EfficientNet-B0 ONNX binary classifier from the project `.venv`, and the collection/analysis harness now exists. However, no confirmed current official elderly target-camera RTSP stream or same-camera recorded replay has been provided in this workspace.

Current gates:

- `POST_FALL_V2_DOMAIN_DATASET_BLOCKED`
- `POST_FALL_V2_THRESHOLD_TRANSFER_NOT_RUN`
- `POST_FALL_V2_BINARY_DOMAIN_VALIDATION_BLOCKED`
- `P3_ALLOWED=NO`

Reason: `DOMAIN_COLLECTION_BLOCKED_NO_TARGET_CAMERA_DATA`.

This `P3_ALLOWED=NO` state must remain until formal target-camera replay or live RTSP evidence is available and analyzed. Existing fixture, private acceptance, mock, downloaded, generated, or legacy training videos are not counted as current elderly target-camera domain evidence.

Execution materials:

- `docs/post_fall_v2_target_camera_data_acquisition_protocol.md`
- `artifacts/post_fall_v2/domain_evidence/p2_5c_target_camera_session_plan.csv`
- `artifacts/post_fall_v2/domain_evidence/manifest_template.json`

The 30-session P2.5C plan dry-run validated successfully:

- sessions: `30`
- calibration sessions: `18`
- acceptance sessions: `12`
- split manifest SHA256: `5248aa3181e12e23581df9a39b7bb4a23cd45c673de681f51990067ec3087e3a`

## Runtime Environment Check

Verified project venv:

- Python executable: `E:\国赛\camera-service\.venv\Scripts\python.exe`
- `onnxruntime`: available
- `onnxruntime` version: `1.23.2`
- Providers: `AzureExecutionProvider`, `CPUExecutionProvider`

Current `.env` was inspected but not modified:

- `VISION_SERVICE_RUNTIME_PROFILE=safe_demo`
- `PIPELINE_MODE=legacy`
- `DEFAULT_RTSP_URL=` empty
- `MOCK_CAMERA_ENABLED=true`
- `EVENT_VLM_ENABLED=false`
- `EVENT_DELIVERY_ENABLED=false`
- `MAIN_SYSTEM_ALERT_ENABLED=false`

Because the current runtime source is mock/demo and no target-camera URL or target-camera replay is confirmed, runtime/demo output cannot be counted as domain evidence.

## Added Tooling

New collection tool:

- `tools/run_post_fall_v2_domain_collection.py`

Purpose:

- Load a session manifest from JSON or CSV.
- Validate scenario labels, `binary_ground_truth`, source type, and session-level split.
- Run target RTSP/live or target-camera replay through the existing P2 `FallBinaryClassifierService`.
- Preserve `FULL_FRAME_TRAIN_MATCHED` classifier input policy.
- Write frame-level domain evidence under `artifacts/post_fall_v2/domain_evidence/`.
- Freeze `domain_split_manifest.json` and record its SHA256 before analysis.
- Keep VLM, incident creation, external POST, alerts, and FallCandidate out of scope.

New analysis tool:

- `tools/analyze_post_fall_v2_domain_evidence.py`

Purpose:

- Read domain frame JSONL evidence.
- Enforce session-level calibration/acceptance split disjointness.
- Evaluate fixed threshold transfer with `0.3979087471961975` on `DOMAIN_ACCEPTANCE`.
- Compute frame-level metrics: TP, FP, TN, FN, precision, recall, specificity, FPR, F1, ROC-AUC, PR-AUC.
- Compute per-scenario probability distributions.
- Compute per-session clip statistics and longest consecutive above/below threshold.
- Report hard negatives separately with `HARD_NEGATIVE_FALSE_POSITIVE_RATE`.
- Report `POST_FALL_BOOTSTRAP_SCENARIO` and `POST_FALL_RECONNECT_SCENARIO` first-hit/early-window statistics when present.
- Run optional candidate threshold sweep only on `DOMAIN_CALIBRATION`; output is a proposal, not a production threshold.

## Scenario Contract

Supported labels:

- Normal noFall: `standing`, `walking`, `sitting`, `bending`, `squatting`, `kneeling`
- Hard negatives: `lying_bed`, `lying_sofa`, `lying_floor_normal`, `exercise_floor`
- Fall/post-fall: `fallen_floor_supine`, `fallen_floor_prone`, `fallen_floor_side`, `fallen_near_furniture`, `partial_occlusion_fallen`
- Other: `no_person`, `unknown`

Special scenario markers:

- `POST_FALL_BOOTSTRAP_SCENARIO`
- `POST_FALL_RECONNECT_SCENARIO`

The tooling rejects scenario/binary-ground-truth mismatches, for example `lying_bed=Fall`.

Formal manifest fields now include:

- `session_id`, `camera_id`, `camera_position_version`, `room_id`, `actor_id`
- `scenario_label`, `binary_ground_truth`, `split`
- `lighting`, `distance_category` or `distance`, `occlusion_level` or `occlusion`
- `source_type`, `source_path` or `source_url`, `recorded_at`
- `resolution`, `source_width`, `source_height`
- `sample_fps`, `input_policy`, `special_scenarios`

## Current Evidence Result

Generated blocked-state analysis artifact:

- `artifacts/post_fall_v2/domain_evidence/no_target_camera_data/threshold_transfer_report.json`
- `artifacts/post_fall_v2/domain_evidence/no_target_camera_data/post_fall_v2_current_camera_domain_evidence_report.md`
- `artifacts/post_fall_v2/domain_evidence/no_target_camera_data/clip_session_statistics.csv`
- `artifacts/post_fall_v2/domain_evidence/no_target_camera_data/scenario_probability_stats.csv`

Current evidence summary:

- Recording sessions: `0`
- Valid frames: `0`
- Domain evidence source: none
- Current official target camera: not confirmed
- Target-camera replay: not confirmed
- Fall/noFall frames: `0 / 0`
- Hard negatives covered: no
- `POST_FALL_BOOTSTRAP_SCENARIO`: not run
- `POST_FALL_RECONNECT_SCENARIO`: not run
- Threshold transfer result: not run
- Acceptance result: not run
- Domain candidate threshold proposal: none

Workspace video scan found only non-qualifying existing videos:

- `person_boxes_3ede20bdbd5d78fa510228ff994f1fda.mp4`
- `private_test_assets\fall_replay_acceptance_derived_hold.mp4`
- `private_test_assets\fall_replay_acceptance.mp4`
- `tests\fixtures\person_bus_loop.mp4`
- `tests\fixtures\identity_self_loop.mp4`
- `tests\fixtures\7992a66e51c7700a23f5e3798321077d.mp4`

None of these has evidence proving it is from the current official elderly target camera, so none was used for Domain Validation.

## Usage

Write a manifest template:

```powershell
.\.venv\Scripts\python.exe tools\run_post_fall_v2_domain_collection.py --write-template artifacts\post_fall_v2\domain_evidence\manifest_template.json
```

Run collection from a confirmed target-camera manifest:

```powershell
.\.venv\Scripts\python.exe tools\run_post_fall_v2_domain_collection.py --manifest path\to\domain_manifest.json
```

Run analysis on a collection output directory:

```powershell
.\.venv\Scripts\python.exe tools\analyze_post_fall_v2_domain_evidence.py --input artifacts\post_fall_v2\domain_evidence\<run_id>
```

Emit blocked gates when no target-camera data exists:

```powershell
.\.venv\Scripts\python.exe tools\analyze_post_fall_v2_domain_evidence.py --input artifacts\post_fall_v2\domain_evidence\no_target_camera_data\domain_frame_results.jsonl --output-dir artifacts\post_fall_v2\domain_evidence\no_target_camera_data --allow-empty
```

## Safety Boundaries

This phase did not:

- Modify the real `.env`
- Enable `POST_FALL_V2_SHADOW_ENABLED`
- Implement `FallCandidateService`
- Implement temporal candidate aggregation
- Call Qwen, Ollama, or any VLM
- Create incidents
- Send alerts
- POST to the main system
- Replace the legacy pipeline

## Next Required Input

To move the gates, provide either:

- The current official elderly target-camera RTSP URL and safe collection window, or
- Recorded videos from that same target camera, grouped as recording sessions with scenario labels.

The first formal collection should include both `DOMAIN_CALIBRATION` and `DOMAIN_ACCEPTANCE`, with complete session-level split and hard-negative coverage before any Domain READY claim.

Recommended first execution target:

- 24 to 36 recording sessions
- 10 to 20 seconds per session
- At least 2 independent sessions for each core scenario where feasible
- Required hard negatives: `lying_bed`, `lying_sofa`, `lying_floor_normal`
- Required fall scenarios: `fallen_floor_supine`, `fallen_floor_side`, `fallen_floor_prone`
- Ensure `far + fallen` appears at least once
- Try to include `POST_FALL_BOOTSTRAP_SCENARIO`; add `POST_FALL_RECONNECT_SCENARIO` through safe replay if possible

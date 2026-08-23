# Legacy 69 Service Skeleton Audit - 2026-06-21

## Summary

- legacy_repo_url: `https://github.com/kangzhouyang/69-service-`
- legacy_branch: `main`
- legacy_commit: `fccce1dc612e21b0e3bced994a123413448a49ee`
- audit_checkout: `D:\Program\legacy_sources\69-service-good-candidate`
- checkout_result: `PASS`
- legacy_pose_audit: `PASS`
- legacy_bridge_audit: `PASS`
- adapter_added: `NOT_RUN`
- provider_added: `NOT_RUN`
- recommendation: `KeepNoPoseProduction`

The legacy project does contain a real backend YOLO pose estimator and frontend
skeleton rendering. The reusable skeleton format is COCO17. However, the core
backend file `app/pose/yolo_pose_estimator.py` is byte-for-byte identical to the
current repository's `app/pose/yolo_pose_estimator.py`, and the legacy checkout
does not contain pose model weights. Re-adding this as a new provider would
mostly re-enable the same YOLO pose path that the current no-pose placeholder
baseline intentionally took offline.

## Candidate Pose Files

- `app/pose/yolo_pose_estimator.py`
- `app/pose/pose_estimator.py`
- `app/pose/schemas.py`
- `app/pose/mock_pose_estimator.py`
- `app/services/pose_service.py`
- `app/services/pose_worker_service.py`
- `tests/test_yolo_pose_estimator.py`

Backend capability found:

- Uses Ultralytics `YOLO`.
- Accepts current video frame plus detected/tracked `DetectedObject` boxes.
- Crops around the input bbox.
- Runs pose inference on each crop.
- Restores keypoint coordinates back to full-frame pixel coordinates.
- Selects the best pose candidate by bbox IoU, keypoint-inside-bbox ratio,
  skeleton confidence, torso-inside-bbox, and detector confidence.
- Rejects misaligned pose candidates with reasons such as
  `keypoints_outside_bbox`, `candidate_bbox_mismatch`, and `torso_outside_bbox`.

## Candidate Frontend Overlay Files

- `frontend_demo/overlay.js`
- `frontend_demo/app.js`
- `frontend_demo/index.html`

Frontend capability found:

- Draws COCO-style skeleton segments.
- Filters low-confidence keypoints.
- Rejects rejected pose payloads.
- Has a short overlay pose cache and smoothing path.
- Checks pose alignment against object bbox before drawing.

Current frontend already has stricter no-pose/placeholder guards than the legacy
overlay, including placeholder badges and stale/frame/track/bbox checks.

## Candidate Model Files

No pose model binary is present in the isolated legacy checkout.

- `YOLO_POSE_MODEL_PATH=yolov8n-pose.pt` is configured in `.env.example`.
- `*.pt`, `*.pth`, `*.onnx`, and `*.engine` are ignored by legacy `.gitignore`.
- The probe used current local weights from `D:\Program\vision_service`, not
  weights committed in the legacy checkout.

candidate_model_files: `NONE_IN_LEGACY_CHECKOUT`

## Keypoint Format

legacy_keypoint_format: `COCO17`

The legacy keypoint order is:

```text
nose, left_eye, right_eye, left_ear, right_ear,
left_shoulder, right_shoulder, left_elbow, right_elbow,
left_wrist, right_wrist, left_hip, right_hip,
left_knee, right_knee, left_ankle, right_ankle
```

keypoint_mapping_required: `false`

The keypoint names/order match the current `new_pose_v1` COCO17 contract, so no
semantic mapping table is required. A wrapper would still need to convert the
legacy `PoseResult` shape into the richer `new_pose_v1` payload fields.

## Pose Runtime Dependencies

Required runtime dependencies:

- `ultralytics`
- `opencv-python`
- `numpy`
- `pydantic`

Local dependency import probe:

- `cv2=OK`
- `numpy=OK`
- `ultralytics=OK`
- `fastapi=OK`
- `pydantic=OK`
- `requests=OK`

## Skeleton Rendering Path

Backend path:

```text
PoseWorkerService
-> PoseService.enrich
-> YoloPoseEstimator.estimate
-> DetectedObject.pose
-> ResultPublisherService
-> WebSocket/integration latest
```

Frontend path:

```text
frontend_demo/app.js composeOverlayResult
-> frontend_demo/overlay.js collectPoseState
-> drawBodyPartSkeleton
```

## Pose And Fall Coupling

legacy_pose_decoupled_from_fall: `false`

The legacy pose output is not display-only by design. It can feed:

- `app/temporal/target_feature_extractor.py`
- `app/temporal/feature_vectorizer.py`
- `app/temporal/fall_state_machine.py`
- `app/behavior/feature_extractor.py`
- `app/behavior/rules.py`

The legacy temporal feature vector contains:

- `pose_available`
- `pose_confidence`
- `torso_angle_norm`
- `head_height_ratio_filled`
- `hip_height_ratio_filled`

This means the old runtime cannot be re-enabled wholesale without risking pose
influence on fall state/risk/incident behavior.

## Bridge Config Files

Bridge-related files:

- `.env.example`
- `app/core/config.py`
- `app/services/fall_event_reporter_service.py`
- `app/services/alert_simulator_service.py`
- `app/api/alerting_api.py`
- `tests/test_alerting_manual_send.py`
- `frontend_demo/app.js`

Legacy bridge target found:

- `MAIN_SYSTEM_BASE_URL=http://192.168.8.254:8000/api/v1`
- `MAIN_SYSTEM_FALL_EVENT_PATH=/video-bridge/fall-events`
- `MAIN_SYSTEM_ALERT_TOKEN_HEADER=X-Vision-Service-Token`
- frontend manual alert default IP: `192.168.8.254`
- alert simulation endpoint: `/alerting/simulation/send-once`

Bridge config appears scoped to alert delivery and simulation. It is not part of
the pose provider itself.

## Current Bridge Comparison

Current code supports the same alert path:

- `app/api/alerting_api.py`: `/alerting/simulation/send-once`
- `app/services/alert_simulator_service.py`: builds
  `/api/v1/video-bridge/fall-events`
- `app/services/fall_event_reporter_service.py`: uses
  `MAIN_SYSTEM_BASE_URL + MAIN_SYSTEM_FALL_EVENT_PATH`

Current code defaults:

- `MAIN_SYSTEM_BASE_URL=http://127.0.0.1:8090/api/v1`
- `MAIN_SYSTEM_FALL_EVENT_PATH=/video-bridge/fall-events`
- `MAIN_SYSTEM_ALERT_TOKEN_HEADER=X-Vision-Service-Token`

Current local `.env` differs from the user-recorded bridge target:

- local `.env` has `MAIN_SYSTEM_BASE_URL=http://192.168.8.253:8000/api/v1`
- user/legacy record expects `http://192.168.8.254:8000/api/v1`

Token presence was detected in local `.env`, but the value is intentionally not
included here.

bridge_target_found: `PASS`
bridge_target_matches_user_record: `PASS_IN_LEGACY_ENV_EXAMPLE`
current_bridge_target_matches_user_record: `FAIL`
recommended_bridge_action: `NeedBridgeTargetSync`

No bridge configuration was modified.

## Standalone Probe

legacy_standalone_probe: `PASS_WITH_EXTERNAL_WEIGHTS`

Probe output:

- `D:\Program\vision_service\logs\legacy_69_service_skeleton_probe_20260621\probe_report.md`
- `D:\Program\vision_service\logs\legacy_69_service_skeleton_probe_20260621\output_keypoints.jsonl`
- `D:\Program\vision_service\logs\legacy_69_service_skeleton_probe_20260621\rendered_preview`
- `D:\Program\vision_service\logs\legacy_69_service_skeleton_probe_20260621\dependency_report.txt`

Probe safety:

- Did not start legacy FastAPI service.
- Did not bind port `8000` or `8012`.
- Did not call `/alerting/*`.
- Did not post to the main system.
- Did not modify runtime config.
- Did not train.

Probe input:

- Used current curated frame images from
  `D:\Program\vision_service\datasets\new_pose_frames\camera_01`.
- Used current local `D:\Program\vision_service\yolov8n.pt` for person bbox.
- Used current local `D:\Program\vision_service\yolov8n-pose.pt` for pose.

Probe result:

| sample | result | valid keypoints | skeleton confidence | pose latency ms |
| --- | --- | ---: | ---: | ---: |
| `standing_front` | PASS | 17 | 0.8868 | 198.88 |
| `standing_side` | PASS | 17 | 0.9415 | 202.89 |
| `walking_slow` | PASS | 17 | 0.9025 | 109.17 |
| `lying_back` | PASS | 17 | 0.9076 | 209.71 |
| `fall_simulated_back` | PASS | 16 | 0.8574 | 117.03 |

Important caveat: this proves the legacy estimator code can run on this machine
when supplied with current local YOLO weights and a person bbox. It does not
prove that the legacy repo is self-contained, because it does not include those
weights.

## Reuse Scoring

reusable_pose_score: `MEDIUM`

Reason:

- Positive: real backend COCO17 keypoint output exists.
- Positive: frontend skeleton rendering exists.
- Positive: offline single-frame probe passes with local weights and detected bboxes.
- Negative: no model weights in legacy checkout.
- Negative: backend estimator already exists unchanged in current repo.
- Negative: old runtime is not display-only; pose can feed temporal/behavior/fall features.

reusable_bridge_score: `HIGH`

Reason:

- Bridge target and header convention are clearly documented in legacy config.
- Current code already has the same alert simulation endpoint and bridge path.
- Config mismatch should be handled as a bridge target sync decision, not as part
  of pose provider migration.

## Migration Risks

- Re-enabling `POSE_PROVIDER=yolo` would reactivate a path intentionally removed
  from production runtime because of pose drift.
- The old estimator is already present in the current codebase, so a
  `legacy_69_skeleton` provider would mostly duplicate the same implementation.
- Legacy runtime allows pose-derived features to influence temporal/fall logic.
- Legacy checkout does not pin a model binary, so results depend on whatever
  local/downloaded YOLO pose weight is used.
- Frontend cache/smoothing from the old overlay is weaker than the current
  placeholder/stale guards.
- Current local `.env` bridge target differs from the user-recorded
  `192.168.8.254:8000` target.

## Recommendation

recommended_action: `KeepNoPoseProduction`

Do not add `Legacy69SkeletonAdapter` or `legacy_69_skeleton` provider in this
round. The safest path is:

1. Keep current production defaults at `ENABLE_POSE=false` and
   `POSE_PROVIDER=disabled_placeholder`.
2. Do not use legacy pose for `fallen_confirmed`, `risk_level`, or incident
   generation.
3. Treat the old code as a reference implementation for COCO17 output shape and
   frontend drawing, not as a new stable provider.
4. If a temporary display-only provider is still desired later, wrap the existing
   current `YoloPoseEstimator` behind a strict `new_pose_v1` adapter with
   `shadow_only=true`, `use_for_fall=false`, frame/track/bbox freshness gates,
   model-load fallback to `disabled_placeholder`, and explicit operator opt-in.
5. Separately decide whether to sync current bridge target to
   `http://192.168.8.254:8000/api/v1`; do not tie that change to pose migration.

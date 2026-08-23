# Vision Service Current Issue Inventory

Updated: `2026-06-20`
Repository: `D:\Program\vision_service`
Branch: `main`
Commit: `66b5b82`
Source of facts: local git state, live local APIs, existing evidence directories

---

## 1. Executive Summary

The current top problem is **not** further Pose tuning.

The real blockers right now are:

1. `camera_01` does not produce a fresh frame
2. the current live runtime is **not** the same runtime profile used during the last accepted staging fixes
3. because there is no fresh frame, real-person retest and unified end-to-end acceptance are blocked
4. the repository is currently a dirty worktree with many parallel experiments and migration files

Practical conclusion:

> The next correct step is to restore fresh frame under the correct runtime configuration, not to keep tuning Pose, thresholds, or field rules blindly.

---

## 2. Current Live Runtime Snapshot

Local checks on `2026-06-20`:

- `GET /healthz` -> `200`, body: `{"status":"ok"}`
- `GET /status` -> service is running, but `camera_01` is not connected
- `GET /stream/latest-frame.jpg` -> `404`

Key values from `/status`:

### Camera status

- `service_status = running`
- `camera_id = camera_01`
- `running = true`
- `connected = false`
- `stream_state = connecting`
- `frame_seq = 0`
- `capture_fps = 0.0`
- `frame_age_ms = null`
- `reconnect_count = 48`
- `reconnect_reason = open_failed`
- `last_error = source open failed`
- `capture_process_alive = false`

### Detection / tracking / pose / temporal status

- `latest_raw_person_count = 0`
- `latest_fall_model_count = 0`
- `tracked_objects_count = 0`
- `tracking_state = idle`
- `pose_provider = yolo`
- `pose_fps = 0.0`
- `temporal.enabled = false`
- `temporal.model_provider = mock`
- `latest_result.latest_objects_count = 0`
- `latest_result.alarm_confirmed = false`
- `latest_result.incident_id = null`

### Critical configuration mismatch

The previously targeted staging runtime for live acceptance was:

- `runtime_profile = current_camera_live`
- `POSE_PROVIDER = branch4_legacy`

The **current** live runtime is:

- `runtime_profile = default`
- `pose_provider = yolo`
- `temporal.enabled = false`
- `model_provider = mock`

This means:

> The currently running service is not the same controlled pipeline that was used for the recent false-positive and field-rule fixes.

---

## 3. Current Issue List

## P0. Camera fresh frame is not available

### Symptoms

- `/stream/latest-frame.jpg` returns `404`
- `camera_01` stays in `stream_state=connecting`
- `frame_seq=0`
- `capture_fps=0.0`
- `reconnect_reason=open_failed`
- `last_error=source open failed`

### Impact

- no live frame is available
- detection, tracking, pose, and temporal live validation cannot proceed
- `/demo` cannot be used for live operator acceptance
- unified acceptance with the main system cannot continue

### Assessment

This is the **first hard blocker**.

---

## P0. Current runtime configuration does not match the last accepted staging configuration

### Symptoms

Historically accepted target runtime:

- `branch4_legacy`
- `current_camera_live`

Current runtime:

- `runtime_profile=default`
- `pose_provider=yolo`
- `temporal.enabled=false`
- `model_provider=mock`

### Impact

- current live observations are not representative of the intended target pipeline
- even if the camera is restored, validation under the wrong runtime may produce misleading conclusions
- this can create false negatives such as "the code was fixed, but the wrong runtime was tested"

### Assessment

This is a blocker at the same level as fresh frame recovery.

---

## P0. Real-person retest and unified acceptance are currently blocked

### Blocked acceptance items

- no-person safety retest
- standing / sitting false-positive retest
- real fall chain retest:
  - `normal`
  - `falling`
  - `fallen_candidate`
  - `fallen_confirmed`
- full result chain retest:
  - `incident_id`
  - `snapshot`
  - `integration latest`
  - `poll`
  - `ws`

### Blocking reasons

- no fresh frame
- current runtime is not the intended staging runtime

### Assessment

This is not a new algorithm failure by itself.
It is a case of **acceptance preconditions not being satisfied**.

---

## P1. Dirty worktree creates a high risk of accidental misdevelopment

### Symptoms

`git status --short` currently shows many modified and untracked files across:

- `app/pose/*.py`
- `app/services/*.py`
- `app/temporal/fall_state_machine.py`
- `frontend_demo/*`
- `scripts/*`
- `tests/*`
- `docs/*`
- `models/rtmpose/*`
- `video/*`

Examples include:

- `app/pose/branch4_legacy_pose_estimator.py`
- `app/pose/yolo11_legacy_pose_estimator.py`
- `app/pose/rtmpose_estimator.py`
- `app/pose/rtmpose_onnx_estimator.py`
- multiple benchmark, export, and compare scripts
- multiple handoff, API, and integration documents

### Impact

- a new engineer can easily pick the wrong provider, script, or entrypoint
- it is hard to tell which files are experimental and which files are the intended source of truth
- it increases the chance of editing the wrong chain

### Assessment

This is an engineering workflow risk, not a direct model bug, but it materially slows handoff and stabilization.

---

## P1. Final live closure after the field-rule fix is still not complete

### Historically fixed issues

The following were already investigated and minimally fixed:

1. no-person scene could produce `fallen_confirmed + incident_id` because a fall-only box was promoted to person tracking
2. sitting could be falsely confirmed by stale strong hint + coarse field-grid accumulation
3. `field_rules_not_met` lacked explainable debug output

Key commits:

- `4802ae5`
  - `fix: require person evidence for fall-only confirmation`
- `66b5b82`
  - `fix: require current fall evidence for field confirmation`

### What is still not re-closed in live runtime

Until camera and runtime are restored, the following still lack fresh final validation:

- sitting remains stable and does not become `fallen_confirmed`
- a real fall still reaches `fallen_confirmed`
- `snapshot`, `incident_id`, and integration result publishing all work in the live chain

### Assessment

This is not "confirmed broken again".
It is "final closure is pending because the live retest conditions are not available yet".

---

## P2. Pose is no longer the top blocker, but its history still matters

### Historical pose problems already investigated

- bbox correct but skeleton offset
- stale pose reuse
- wrong pose to `track_id` binding
- full-frame pose candidate matching worse than target-only crop pose
- low-confidence leg points and edge points polluting `pose_bounds`

### Historical conclusion

The useful part of the `branch4` style pipeline was mainly:

- target-only ROI crop pose
- `yolo11n-pose.pt`
- offset-based coordinate restore
- per-track smoothing
- low-confidence and edge-point filtering for legs

### Assessment

Pose should **not** be the next blind tuning target.
Its priority is lower than:

1. fresh frame recovery
2. correct runtime recovery
3. live retest closure

---

## P2. Documentation encoding/readability issue exists

### Symptoms

Some existing documents show mojibake or unreadable Chinese in the current terminal environment, for example:

- `docs/project_integration_guide_2026-06-19.md`
- `docs/interface_api_spec_2026-06-19.md`

### Impact

- onboarding becomes slower
- documents may exist but still be hard to consume quickly

### Assessment

This is not a runtime blocker, but it is a real handoff efficiency issue.

---

## P2. End-to-end demo path depends on another repository

### Current state

The main-system frontend `video-bridge` popup wiring was completed in:

- repository: `D:\Program\410health`
- commit: `845e6c5`
- message: `feat: wire video bridge fall alerts to frontend`

That work already covers:

- frontend alert list
- global popup
- `/video-bridge/fall-events/poll` polling
- duplicate incident suppression
- successful frontend build
- successful backend regression tests

### Current blocking side is not the frontend

The end-to-end blocker remains on `vision_service`:

- no fresh frame
- wrong live runtime configuration

---

## 4. Resolved vs Unresolved

## Resolved or minimally protected

- no-person `fall-only` false confirmed alert
- detector-only confirm without person evidence
- weak temporal reset for `objects=[]`
- stale incident reuse
- sitting falsely confirmed from stale strong hint + field grid
- lack of explainable `field_rules_not_met` debug
- main-system frontend `video-bridge` popup wiring

## Not yet fully re-closed

- fresh frame recovery
- correct runtime/profile/provider recovery
- final post-`66b5b82` sitting retest
- final post-`66b5b82` real-fall retest
- unified end-to-end live demo

---

## 5. Recommended Order of Work

### Step 1

Restore `camera_01` fresh frame:

- `stream_state=connected`
- `capture_fps>0`
- `frame_age_ms<500`
- `/stream/latest-frame.jpg = 200`

### Step 2

Restore the intended runtime chain, not just any default startup:

- `runtime_profile`
- `pose_provider`
- `temporal.enabled`
- `model_provider`

### Step 3

Run a minimal live retest under the correct runtime:

1. no-person
2. standing
3. sitting
4. real fall

### Step 4

Only after the first three steps pass, continue to:

- unified acceptance
- main-system integration acceptance
- any decision about default provider switching

---

## 6. Three Most Important Handoff Sentences

1. The top current problem is **missing fresh frame**, not more Pose tuning.
2. The currently running service is **not** the same staging chain used during the latest accepted fixes.
3. Any live fall conclusion before fresh frame and correct runtime are restored is unreliable.

---

## 7. Related Documents and Evidence

Recommended documents:

- `docs/engineer_handoff_2026-06-19.md`
- `docs/codex_debug_rules.md`
- `docs/fall_alarm_popup_failure_analysis_2026-06-16.md`
- `docs/project_integration_guide_2026-06-19.md`
- `docs/interface_api_spec_2026-06-19.md`

Important evidence directories:

- `logs/acceptance/real_person_retest_20260618_run2`
- `logs/acceptance/standard_action_retest_20260618_112537`
- `logs/acceptance/real_retest_after_field_fix_20260618_140733`

Main-system frontend integration evidence:

- `D:\Program\410health\logs\acceptance\frontend_video_bridge_wiring_20260620_133456`

# Vision Service Engineer Handoff 2026-06-19

## 1. Purpose

This document is a focused handoff for a new engineer joining the `vision_service` project.
It summarizes the recent debugging and stabilization work around:

- pose overlay alignment
- fall-only false positives
- field-rule based false confirmations
- current live staging acceptance status

Current repository:

- path: `D:\Program\vision_service`
- current commit at handoff time: `66b5b82`
- latest commit message: `fix: require current fall evidence for field confirmation`

## 2. System Goal

The service ingests RTSP video, runs person detection, fall detection, pose estimation, tracking, temporal analysis, and publishes real-time fall results for upstream consumers.

Recent work focused on three practical requirements:

1. no-person scenes must not generate confirmed fall alerts
2. sitting must not be falsely confirmed as a fall
3. real fall scenarios should remain confirmable with evidence that is explainable

## 3. Key Files

Core paths touched during this debugging cycle:

- `app/services/result_publisher_service.py`
- `app/services/tracking_worker_service.py`
- `app/services/temporal_service.py`
- `app/services/fall_event_reporter_service.py`
- `app/services/pose_service.py`
- `app/pose/branch4_legacy_pose_estimator.py`
- `tests/test_result_publisher_service.py`
- `tests/test_tracking_worker_service.py`
- `tests/test_fall_event_reporter_service.py`
- `tests/test_temporal_service.py`

Useful docs already in repo:

- `docs/codex_debug_rules.md`
- `docs/pose_model_upgrade_research_2026-06-14.md`
- `docs/vision_service_followup_for_main_system_plan_2026-06-16.md`
- `docs/fall_alarm_popup_failure_analysis_2026-06-16.md`

## 4. Recent Commit Timeline

- `66b5b82` `fix: require current fall evidence for field confirmation`
- `4802ae5` `fix: require person evidence for fall-only confirmation`
- `057775b` `fix: persist incident id and standardize confirmed fall result`
- `fccce1d` `Update main system bridge target`

## 5. What Was Investigated

### 5.1 Pose / Overlay

Several rounds of investigation were done on:

- bbox normal but pose skeleton offset
- normal state showing red/orange colors
- multi-person pose-to-track mismatches
- stale pose reuse
- branch4 vs staging pose pipeline differences

Conclusions:

- one root cause was stale or mismatched pose reuse
- another root cause was UI color logic reading `risk_level` while text read `fall_state`
- branch4-style target-only crop pose was visually better than full-frame candidate matching
- later residual leg drift was traced to low-confidence edge keypoints polluting `pose_bounds`

Current live provider status:

- pose provider in runtime: `branch4_legacy`
- runtime profile: `current_camera_live`
- live stream currently connected

Important note:

- pose quality work is not the current top priority
- current blocking issue moved to result-layer fall confirmation logic

### 5.2 Fall-only False Positive

Observed failure:

- no visible person in live frame
- system still emitted `fallen_confirmed`
- `incident_id` kept appearing

Root cause found:

- fall-only detector box got promoted into tracking as if it were a person
- detector-only confirm path then confirmed the event

Minimal fix landed in `4802ae5`:

- no unmatched fall-only box may become a tracked person without person evidence
- detector-only confirm now requires real person evidence
- no-object temporal reset was hardened
- stale incident reuse was guarded

Verified outcome:

- no-person scene no longer produces confirmed alerts

## 6. Field Rule Investigation

After the no-person false positive fix, a more subtle problem remained:

- sitting could be confirmed as a fall
- real fall could be dropped by field rules

The key code path is in `app/services/result_publisher_service.py`, especially:

- `_merge_fall_detection()`
- `_merge_weak_fall_hints()`
- `_merge_field_fall_candidates()`
- `_field_fall_candidate_confirmed()`

### 6.1 Sitting False Confirm Root Cause

Observed chain:

- sitting
- `field_fall_candidate_promoted`
- `confirmed=True`
- `incident_id`

Evidence showed that field fusion could confirm a sitting posture because:

- a recent strong fall hint was still remembered
- low-posture bbox conditions passed
- low speed passed
- temporal window was large enough
- field confirm state accumulated by coarse spatial grid rather than stable person identity

### 6.2 Real Fall Miss Root Cause

Observed during standard fall retest:

- repeated `field_fall_candidate_dropped reason=field_rules_not_met`
- repeated `weak_hint_guard_not_met`
- repeated `no_fall_objects`

Interpretation:

- field rule depended too much on strong current or recent fall hints
- when current fall detector output disappeared, field fusion lacked explainability
- logs did not clearly state which exact conditions were missing

## 7. Minimal Structural Fix Landed in 66b5b82

Commit `66b5b82` addressed the field confirmation path without changing thresholds.

### 7.1 Fixes Included

1. field confirmation no longer confirms from historical hint alone when the current frame has no fall object
2. field confirmation state key now includes `track_id` in addition to spatial grid
3. field confirmation requires stable person evidence instead of pure grid accumulation
4. sitting-like cases are blocked from direct field confirmation when only weak/current evidence exists
5. field-rule debug now records missing conditions and contributing signals

### 7.2 New Field Debug Signals

The field rule path now emits structured debug information such as:

- `has_recent_strong_hint`
- `has_current_fall_object`
- `has_current_strong_fall_object`
- `aspect`
- `aspect_pass`
- `center_y_norm`
- `center_y_pass`
- `height_norm`
- `height_pass`
- `window_size`
- `window_size_pass`
- `speed`
- `speed_pass`
- `stable_track`
- `stable_track_pass`
- `person_evidence`
- `person_evidence_pass`
- `pose_available`
- `body_angle`
- `low_posture`
- `stillness`
- `velocity_y`
- `bbox_aspect_ratio`
- `candidate_duration_ms`
- `confirm_duration_ms`
- `missing_conditions`
- `promotion_reason`
- `drop_reason`

### 7.3 New Rejection Reasons

The latest field rule path may now explicitly return:

- `field_recent_hint_blocked_no_current_fall_object`
- `field_confirm_requires_stable_person_evidence`
- `field_confirm_blocked_possible_sitting`
- `awaiting_field_confirm_frames_or_duration`

## 8. Test Status

The following local tests passed after `66b5b82`:

- `python -m pytest tests/test_result_publisher_service.py -q`
- `python -m pytest tests/test_result_publisher_service.py tests/test_fall_event_reporter_service.py tests/test_tracking_worker_service.py tests/test_temporal_service.py -q`

Result summary:

- `12 passed`

Protected cases now covered:

- field confirm blocked when no current fall object
- field confirm requires stable person evidence, not only grid key
- sitting-like low posture should not confirm from stale recent hint
- field rules include `missing_conditions`
- no-person false positive regression remains fixed

## 9. Evidence Directories

Useful recent evidence directories:

- `logs/acceptance/false_positive_fix_20260618_1000`
- `logs/acceptance/real_person_retest_20260618_run2`
- `logs/acceptance/standard_action_retest_20260618_112537`
- `logs/acceptance/real_retest_after_field_fix_20260618_140733`

Meaning:

- `real_person_retest_20260618_run2`
  - older live retest where candidate was brief and not confirmed
- `standard_action_retest_20260618_112537`
  - critical evidence set that exposed:
    - sitting false confirm
    - real fall dropped by field rules
- `real_retest_after_field_fix_20260618_140733`
  - acceptance capture prepared after `66b5b82`
  - this should be the next evidence source to review after真人动作完成

## 10. Current Runtime Snapshot

At handoff time, status API showed:

- runtime profile: `current_camera_live`
- pose provider: `branch4_legacy`
- stream state: `connected`
- capture fps: about `9`
- frame age: under `100 ms`
- tracking state was seen in `target_reacquiring`
- temporal state was `normal`

Important:

- live runtime is working
- no-person baseline was clean at the time the new retest sampler was started

## 11. What Is Still Pending

The most important remaining task is not code design but real-scene validation after `66b5b82`.

Required live checks:

1. no-person scene remains clean
2. sitting does not become `fallen_confirmed`
3. real fall can still reach:
   - `falling`
   - `fallen_candidate`
   - `fallen_confirmed`
   - `alarm_confirmed=true`
   - `incident_id!=null`
   - snapshot generated

This needs to be evaluated from:

- `logs/acceptance/real_retest_after_field_fix_20260618_140733/status_samples.jsonl`
- matching runtime logs in `logs/codex_false_positive_fix_8001.out.log`

## 12. Recommended Next Workflow For New Engineer

Suggested order:

1. review `66b5b82` changes in `result_publisher_service.py`
2. read `tests/test_result_publisher_service.py` to understand protected scenarios
3. inspect `logs/acceptance/standard_action_retest_20260618_112537`
4. inspect `logs/acceptance/real_retest_after_field_fix_20260618_140733`
5. run a fresh live acceptance pass if the newest retest is incomplete
6. only after evidence review, decide whether the next blocker is:
   - tracking stability
   - pose drop
   - field rule logic
   - temporal confirmation
   - result publication

## 13. Constraints To Keep In Mind

Repeated project constraints from recent work:

- do not change RTSP just to bypass logic bugs
- do not change YOLO or pose weights unless there is strong evidence
- do not loosen thresholds blindly to make real-fall pass
- prefer minimal structural fixes over broad threshold changes
- do not revert unrelated local changes in the dirty worktree

## 14. Practical Takeaway

If the new engineer only remembers three things, they should be these:

1. `4802ae5` fixed the no-person fall-only false positive at the detector/result boundary
2. `66b5b82` fixed the field confirmation path so sitting should no longer confirm from stale historical hint alone
3. the next decision must come from live evidence review, not from more speculative tuning

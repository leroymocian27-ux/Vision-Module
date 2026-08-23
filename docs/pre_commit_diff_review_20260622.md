# Pre-Commit Diff Review - 2026-06-22

## Purpose

This review exists to prevent accidental staging of unrelated prior-stage work. Do not use broad staging commands in this worktree.

Forbidden commands:

```bash
git add .
git commit -am "..."
```

Use precise staging only.

## A. Replay / Stable Demo Files To Consider Staging

These files belong to the fall replay stable demo handoff and can be considered together:

```text
app/camera/capture_worker.py
tests/test_capture_worker_replay.py
docs/fall_replay_dryrun_final_handoff_20260622.md
docs/stable_demo_runbook_20260622.md
docs/pre_commit_diff_review_20260622.md
```

Recommended precise staging:

```bash
git add app/camera/capture_worker.py
git add tests/test_capture_worker_replay.py
git add docs/fall_replay_dryrun_final_handoff_20260622.md
git add docs/stable_demo_runbook_20260622.md
git add docs/pre_commit_diff_review_20260622.md
```

Suggested commit scope:

```text
Add safe local replay throttle and stable demo handoff docs
```

## B. Bridge Dry-Run Guard Files To Review Separately

These files appear related to the bridge dry-run guard and alerting status work from earlier stages. If committed, use a separate commit from the replay throttle work.

```text
.env.example
app/core/config.py
app/services/fall_event_reporter_service.py
app/schemas/alerting.py
app/api/alerting_api.py
tests/test_fall_event_reporter_service.py
tests/test_result_publisher_service.py
tests/test_alerting_manual_send.py
tests/test_end_to_end_pipeline.py
docs/bridge_integration_final_handoff_20260621.md
```

Possible separate commit scope:

```text
Add bridge reporter dry-run guard and alerting status exposure
```

Review this group carefully before staging. Do not mix it with replay throttle unless intentionally creating a combined release commit.

## C. REVIEW_REQUIRED_DO_NOT_STAGE_BLINDLY

The following files are present in `git status` / `git diff` but are not part of the replay handoff group or the bridge dry-run group above. They require manual review before any staging.

```text
README.md
app/detection/object_detector.py
app/detection/yolo_fall_detector.py
app/main.py
app/pose/schemas.py
app/schemas/status.py
app/schemas/stream.py
app/services/alert_simulator_service.py
app/services/detection_service.py
app/services/pose_service.py
app/services/pose_worker_service.py
app/services/status_service.py
app/services/stream_service.py
app/services/temporal_service.py
app/temporal/fall_state_machine.py
app/temporal/target_feature_extractor.py
frontend_demo/app.js
frontend_demo/index.html
frontend_demo/overlay.js
requirements.txt
scripts/health_main_integration_acceptance.py
scripts/monitor_fall_alert_e2e.py
scripts/run_phase5_dataset_eval.py
scripts/start_current_camera.py
scripts/start_phase5_test.py
tests/test_fall_alert_polling_api.py
tests/test_temporal_service.py
app/pose/branch4_legacy_pose_estimator.py
app/pose/new_pose_schema.py
app/pose/placeholders.py
app/pose/rtmpose_estimator.py
app/pose/rtmpose_onnx_estimator.py
app/pose/yolo11_legacy_pose_estimator.py
artifacts/
docs/codex_debug_rules.md
docs/current_issue_inventory_2026-06-20.md
docs/engineer_handoff_2026-06-19.md
docs/fall_alarm_popup_failure_analysis_2026-06-16.md
docs/interface_api_spec_2026-06-19.md
docs/interface_function_spec_2026-06-19.md
docs/interface_requirements_2026-06-15.md
docs/legacy_69_service_audit_20260621.md
docs/legacy_69_service_checkout_20260621.md
docs/main_system_interface_status_2026-06-16.md
docs/new_pose_action_script_20260621.md
docs/new_pose_batch_a_quality_triage_20260621.md
docs/new_pose_batch_b_manual_review_20260621.md
docs/new_pose_collection_protocol_20260621.md
docs/new_pose_contract_20260621.md
docs/new_pose_data_audit_20260621.md
docs/new_pose_dataset_structure_20260621.md
docs/new_pose_external_mp4_intake_20260621.md
docs/new_pose_frame_extraction_phase4_20260621.md
docs/new_pose_manual_collection_batch_a_20260621.md
docs/new_pose_manual_collection_batch_b_retake_20260621.md
docs/new_pose_model_training_reintegration_plan_2026-06-21.md
docs/new_pose_reintegration_plan_20260621.md
docs/no_pose_placeholder_change_manifest_20260621.md
docs/no_pose_placeholder_runtime_report_2026-06-21.md
docs/pose_fall_logic_report_2026-06-20.md
docs/pose_model_upgrade_research_2026-06-14.md
docs/pose_upgrade_execution_plan_2026-06-14.md
docs/project_integration_guide_2026-06-19.md
docs/receiver_integration_guide.md
docs/vision_service_followup_for_main_system_plan_2026-06-16.md
evaluations/phase10_pose_adaptation_training_plan_001.json
evaluations/phase10_pose_provider_comparison_001.json
models/rtmpose/
scripts/benchmark_pose_providers.py
scripts/capture_pretest_baseline.py
scripts/evaluate_fall_video_offline.py
scripts/export_pose_adaptation_coco.py
scripts/export_pose_pseudolabels.py
scripts/generate_rtmpose_adaptation_config.py
scripts/pose_ab_compare.py
scripts/prepare_rtmpose_adaptation_training.py
tests/test_branch4_legacy_pose_estimator.py
tests/test_fall_state_machine_debug.py
tests/test_integration_connection_status.py
tests/test_pose_service.py
tests/test_pose_service_provider_selection.py
tests/test_stream_service_single_source.py
tests/test_yolo11_legacy_pose_estimator.py
tools/
video/
```

## D. Current Safety Constraints Before Any Commit

Verify before staging or committing:

```text
MAIN_SYSTEM_REPORT_DRY_RUN=true
ENABLE_POSE=false
POSE_PROVIDER=disabled_placeholder
bridge target=http://192.168.8.254:8000/api/v1/video-bridge/fall-events
```

Do not stage token values. Do not print token values.

## E. Suggested Commit Plan

1. Commit replay/stable demo only:

```bash
git add app/camera/capture_worker.py
git add tests/test_capture_worker_replay.py
git add docs/fall_replay_dryrun_final_handoff_20260622.md
git add docs/stable_demo_runbook_20260622.md
git add docs/pre_commit_diff_review_20260622.md
git commit -m "Add safe local replay demo handoff"
```

2. Commit bridge dry-run guard separately only after review:

```bash
git add .env.example
git add app/core/config.py
git add app/services/fall_event_reporter_service.py
git add app/schemas/alerting.py
git add app/api/alerting_api.py
git add tests/test_fall_event_reporter_service.py
git add tests/test_result_publisher_service.py
git add tests/test_alerting_manual_send.py
git add tests/test_end_to_end_pipeline.py
git add docs/bridge_integration_final_handoff_20260621.md
git commit -m "Add bridge reporter dry-run guard"
```

3. Leave all `REVIEW_REQUIRED_DO_NOT_STAGE_BLINDLY` files unstaged until their scope is understood.

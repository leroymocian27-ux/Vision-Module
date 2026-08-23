# Bridge Integration Final Handoff - 2026-06-21

## Scope

This handoff records the final bridge integration state for the current Vision Service runtime.
It does not introduce pose migration, legacy skeleton providers, fall-state changes, Temporal changes, GRU/LSTM changes, incident/risk logic changes, or snapshot logic changes.

## Bridge Target

Before:

```text
MAIN_SYSTEM_BASE_URL=http://192.168.8.253:8000/api/v1
MAIN_SYSTEM_FALL_EVENT_PATH=/video-bridge/fall-events
```

After:

```text
MAIN_SYSTEM_BASE_URL=http://192.168.8.254:8000/api/v1
MAIN_SYSTEM_FALL_EVENT_PATH=/video-bridge/fall-events
MAIN_SYSTEM_ALERT_TOKEN_HEADER=X-Vision-Service-Token
```

Loaded endpoint:

```text
http://192.168.8.254:8000/api/v1/video-bridge/fall-events
```

Token value was not printed in this handoff.

## Dry-Run Guard

A bridge reporter dry-run guard is available through:

```text
MAIN_SYSTEM_REPORT_DRY_RUN=true
```

When dry-run is enabled, Vision Service still builds local fall event payloads, updates local alert/polling state, and keeps frontend/WebSocket observation working, but skips the real HTTP POST to the main system. The runtime logs a safe marker:

```text
fall_event_report_dry_run skipped_real_post
```

The alerting status endpoint exposes the dry-run flag and token header name, but not the token value.

## One-Shot Real POST Verification

Controlled verification was performed exactly once through:

```text
/alerting/simulation/send-once
```

Result:

```text
HTTP status: 200
ok: true
accepted: true
pushed: true
alarm_id: returned by main system
```

After this one-shot test, dry-run was restored immediately and the Vision Service runtime was restarted.

## Dry-Run Restored

Current safe mode:

```text
MAIN_SYSTEM_REPORT_DRY_RUN=true
```

Post-restore checks:

```text
post_restore_real_post_seen=NO
dry_run_after=true
```

Restore verification observed dry-run skip logs and no post-restore real POST success logs.

## No-Pose Guard

Current production no-pose baseline:

```text
ENABLE_POSE=false
POSE_PROVIDER=disabled_placeholder
pose_model_path=null
pose_fps=0.0
```

No YOLO pose weight was loaded, and `yolov8n-pose.pt` was not used by runtime.

The old `69-service` was not started. No `Legacy69SkeletonAdapter` or `legacy_69_skeleton` provider was added.

## Tests

Regression command:

```bash
python -m pytest tests/test_alerting_manual_send.py tests/test_fall_event_reporter_service.py tests/test_result_publisher_service.py tests/test_fall_alert_polling_api.py tests/test_end_to_end_pipeline.py -q
```

Result:

```text
43 passed, 4 warnings
```

## Current Safe Operating Mode

Local/default validation mode:

```text
MAIN_SYSTEM_REPORT_DRY_RUN=true
```

Only for explicitly approved one-shot bridge tests:

```text
MAIN_SYSTEM_REPORT_DRY_RUN=false
```

After the test, immediately restore:

```text
MAIN_SYSTEM_REPORT_DRY_RUN=true
```

Then restart the current Vision Service and verify `/alerting/status` reports `dry_run=true`.

## Rollback / Safety Note

If there is any uncertainty, keep or restore:

```text
MAIN_SYSTEM_REPORT_DRY_RUN=true
```

Then restart the current Vision Service and confirm:

```text
/alerting/status dry_run=true
/status pose_enabled=false
/status pose_provider=disabled_placeholder
```

Do not call `/alerting/simulation/send-once` unless the user explicitly approves a real one-shot bridge POST. Do not start the old `69-service`.

## Git Diff Scope Note

The bridge handoff scope is limited to bridge dry-run guard/config/status exposure, alerting schemas/API, related tests, and `.env.example` documentation.

The working tree contains pre-existing changes from earlier phases. Review the final staged or committed diff carefully before release to ensure only intended bridge/no-pose handoff changes are included.

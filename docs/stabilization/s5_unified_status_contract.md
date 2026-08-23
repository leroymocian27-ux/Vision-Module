# S5 Unified Status Contract

Date: 2026-07-20
Stage: `S5_UNIFIED_STATUS_AND_DEGRADATION`

## Result

```text
PASS
```

## System Health States

```text
healthy
degraded
blocked
stopped
```

## Fall Business States

Canonical S5 interpretation:

```text
normal
fall_candidate
fall_high_risk
fall_confirmed
cooldown
unavailable
```

Backward-compatible raw values such as `fallen_candidate` and `fallen_confirmed` may remain inside legacy object-level payloads during the RC cycle. Public status helpers normalize them for S5 checks.

## Required Result Fields

The status contract now exposes or derives:

```text
confidence_level
degraded_by
safe_to_interpret_as_no_fall
reason
frame_status
camera_stream_state
source_generation
```

`/status.latest_result` and `/integration/results/{camera_id}/latest` now share the same camera-availability safety rule:

- valid fresh frame: `safe_to_interpret_as_no_fall=true`
- no frame: `fall_state=unavailable`, `safe_to_interpret_as_no_fall=false`
- stale frame: `fall_state=unavailable`, `safe_to_interpret_as_no_fall=false`
- disconnected/stopped/reconnecting/unreachable/auth/decode error: `fall_state=unavailable`, `safe_to_interpret_as_no_fall=false`

## Reason Codes

S5 covers the following reason-code family:

```text
no_frame
camera_disconnected
frame_stale
detector_loading
detector_not_ready
detector_error
tracking_unavailable
pose_disabled
pose_error
temporal_disabled
temporal_warming_up
temporal_error
fusion_error
insufficient_evidence
stale_result
pipeline_stopped
```

Some reason codes are produced immediately by camera/result safety guards; module-specific codes continue to be filled by S6-S8 where event, WebSocket, and full smoke paths exercise them end to end.

## Executed

```powershell
python -m py_compile app\fall\status_contract.py app\schemas\status.py app\schemas\integration.py app\services\status_service.py app\api\integration_api.py tests\stabilization\test_unified_status_contract.py
python -m pytest tests\stabilization\test_unified_status_contract.py -q --maxfail=1
python -m pytest tests\test_fall_alert_polling_api.py -q --maxfail=1
python -m pytest tests\stabilization -q --maxfail=1
git diff -- app\fall\fusion.py
```

## Gate Results

```text
S5_STATUS_CONTRACT_HELPER_GATE: PASS
S5_STATUS_LATEST_RESULT_UNAVAILABLE_GATE: PASS
S5_INTEGRATION_LATEST_RESULT_UNAVAILABLE_GATE: PASS
S5_INTEGRATION_LATEST_RESULT_NORMAL_GATE: PASS
S5_INTEGRATION_COMPATIBILITY_GATE: PASS
S5_STABILIZATION_REGRESSION_GATE: PASS
FALL_FUSION_SERVICE_SEMANTIC_DIFF: NONE
```

## Evidence

```text
app/fall/status_contract.py
tests/stabilization/test_unified_status_contract.py
artifacts/stabilization/S5_UNIFIED_STATUS_AND_DEGRADATION/20260720T112230/summary.json
artifacts/stabilization/S5_UNIFIED_STATUS_AND_DEGRADATION/20260720T112230/pytest_s5.txt
artifacts/stabilization/S5_UNIFIED_STATUS_AND_DEGRADATION/20260720T112230/pytest_integration_compat.txt
artifacts/stabilization/S5_UNIFIED_STATUS_AND_DEGRADATION/20260720T112230/pytest_stabilization.txt
artifacts/stabilization/S5_UNIFIED_STATUS_AND_DEGRADATION/20260720T112230/fall_fusion_diff.txt
```

## Remaining Not Run

```text
S6_EVENT_EVIDENCE_GATE: NOT_RUN
S7_DEMO_WEBSOCKET_GATE: NOT_RUN
S8_FULL_SELF_CHECK_GATE: NOT_RUN
S9_RELEASE_REPRODUCTION_GATE: NOT_RUN
S2_EXTENDED_10_CYCLE_RESTART_CHECK: NOT_RUN
REAL_RTSP_ACCEPTANCE: NOT_RUN
REAL_FALL_ALGORITHM_ACCEPTANCE: NOT_RUN
```

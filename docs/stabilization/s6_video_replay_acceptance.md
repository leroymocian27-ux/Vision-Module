# S6 Video Replay Acceptance Report

Stage: `S6_VIDEO_REPLAY_ACCEPTANCE`
Target version: `fall-monitor-stable-video-replay-v1.0-rc1`
Production ready: `NO`

## Scope

This stage uses an authorized local fall replay video as the controlled source because real RTSP cameras and the real main system are currently unavailable.

The replay source must enter the same main vision chain as RTSP:

`CaptureWorker -> FrameBuffer -> Detection -> Tracking -> Pose -> Temporal -> Fusion -> Result/Event surfaces`

No second inference path, synthetic `fall_confirmed` injection, or FallFusionService threshold/weight/semantic change is allowed.

## Source Handling

The authorized video is stored outside the publishable file set under an ignored local test asset directory. The video file itself, rendered videos, keyframes, person images, timeline images, and screenshots are not eligible for GitHub upload.

Original replay metadata:

| Field | Value |
| --- | --- |
| SHA256 | `bed2891544a6c3e70acceb62250a0fce6c9c2c1133a38bb114cecf92bc2f80e4` |
| Resolution | `1280x720` |
| FPS | `30.0` |
| Frames | `159` |
| Duration | `5.3s` |
| Original media included in repo | `false` |

Derived replay metadata:

| Field | Value |
| --- | --- |
| Source type | `derived_video_replay` |
| SHA256 | `de415b1890a669a3a3efaa22f4a068518b0c01c4003f79008c2ed719ffdebbf4` |
| Resolution | `1280x720` |
| FPS | `30.0` |
| Frames | `459` |
| Duration | `15.3s` |
| Pre-hold | `2.0s` |
| Post-hold | `8.0s` |
| Production acceptance | `false` |
| Algorithm threshold modified | `false` |
| Derived media included in repo | `false` |

## Validation Results

Offline full-pipeline replay results:

| Replay | Detection | Tracking | Pose | Processed Frames | Peak Fall State | Confirmed | Incident |
| --- | --- | --- | --- | ---: | --- | --- | --- |
| Original | `OK` | `OK` | `OK` | `159` | `fallen_candidate` | `FAIL` | `null` |
| Derived hold | `OK` | `OK` | `OK` | `459` | `fallen_candidate` | `FAIL` | `null` |

Online service replay probe results:

| Check | Result |
| --- | --- |
| Local file source accepted by stream start API | `PASS` |
| Frames decoded and published | `PASS` |
| Person detection appeared | `PASS` |
| Fall candidate appeared | `PASS` |
| Fall confirmed appeared | `REVISE` |
| Incident id created | `REVISE` |
| EOF safe interpretation | `PASS` after status contract revision |

EOF status contract:

| Field | Expected |
| --- | --- |
| camera_status | `stopped` |
| reason | `end_of_file` |
| fall_state | `unavailable` |
| safe_to_interpret_as_no_fall | `false` |

## Gate Matrix

| Gate | Status |
| --- | --- |
| VIDEO_REPLAY_SOURCE_GATE | `PASS` |
| VIDEO_REPLAY_DECODE_GATE | `PASS` |
| VIDEO_REPLAY_AI_PIPELINE_GATE | `PASS` |
| VIDEO_REPLAY_FALL_CANDIDATE_GATE | `PASS` |
| VIDEO_REPLAY_FALL_CONFIRMED_GATE | `REVISE` |
| VIDEO_REPLAY_EVENT_GATE | `NOT_RUN` |
| VIDEO_REPLAY_EVIDENCE_GATE | `NOT_RUN` |
| VIDEO_REPLAY_REPEATABILITY_GATE | `NOT_RUN` |
| VIDEO_REPLAY_WEBSOCKET_GATE | `NOT_RUN` |
| VIDEO_REPLAY_DEMO_GATE | `NOT_RUN` |
| MOCK_MAIN_SYSTEM_CONTRACT_GATE | `NOT_RUN` |
| MOCK_MAIN_SYSTEM_IDEMPOTENCY_GATE | `NOT_RUN` |
| FULL_VIDEO_SELF_CHECK_GATE | `BLOCKED` |
| S2_EXTENDED_10_CYCLE_RESTART_CHECK | `NOT_RUN` |
| RELEASE_REPRODUCTION_GATE | `NOT_RUN` |
| SECURITY_SECRET_SCAN_GATE | `NOT_RUN` |
| PRIVACY_MEDIA_SCAN_GATE | `NOT_RUN` |
| LARGE_FILE_SCAN_GATE | `NOT_RUN` |
| README_RELEASE_GATE | `NOT_RUN` |
| GITHUB_PUBLISH_READY_GATE | `BLOCKED` |

Allowed unresolved production items:

| Item | Status |
| --- | --- |
| REAL_RTSP_ACCEPTANCE | `NOT_RUN` |
| REAL_RTSP_RECONNECT_ACCEPTANCE | `NOT_RUN` |
| REAL_MAIN_SYSTEM_ACCEPTANCE | `NOT_RUN` |
| REAL_MAIN_SYSTEM_DELIVERY | `NOT_RUN` |
| PRODUCTION_READY | `NO` |

## Decision

S6 is not publishable yet.

The current user-provided video and the derived hold replay both exercise the main AI pipeline and reach `fallen_candidate`, but neither naturally produces `fall_confirmed` or an `incident_id` under the current FallFusionService semantics.

Therefore:

`VIDEO_REPLAY_FALL_CONFIRMED_GATE: REVISE`

`GITHUB_PUBLISH_READY_GATE: BLOCKED`

GitHub upload, commit, push, or PR creation is not allowed until the required video replay gates pass or the user explicitly changes the release gate policy.

## Files Changed In This Stage

Modified:

- `.gitignore`
- `app/fall/status_contract.py`
- `app/services/status_service.py`
- `tests/stabilization/test_unified_status_contract.py`

Added:

- `docs/stabilization/s6_video_replay_acceptance.md`

Generated local evidence:

- `artifacts/stabilization/S6_VIDEO_REPLAY_ACCEPTANCE/20260720T131150/summary.json`
- `artifacts/stabilization/S6_VIDEO_REPLAY_ACCEPTANCE/20260720T131150/git_status_after.txt`

## Safety Statements

FallFusionService modified: `NO`

Real `.env` modified: `NO`

Real Delivery enabled: `NO`

Real main system POST enabled: `NO`

Robot/Go2/Qwen/Ollama enabled: `NO`

Test media uploaded or made publishable: `NO`

## Verification Commands

```powershell
python -m py_compile app\fall\status_contract.py app\services\status_service.py tests\stabilization\test_unified_status_contract.py
python -m pytest tests\stabilization\test_unified_status_contract.py -q
python scripts\render_fall_video_offline.py --video <local-video-path> --output-dir artifacts\video_replay_probe\offline_original --mode system
python scripts\render_fall_video_offline.py --video <derived-local-video-path> --output-dir artifacts\video_replay_probe\offline_derived --mode system
```

Results:

| Command | Result |
| --- | --- |
| py_compile targeted files | `PASS` |
| unified status contract test | `PASS`, 6 passed |
| offline original replay | `REVISE`, confirmed not produced |
| offline derived replay | `REVISE`, confirmed not produced |

## Rollback

Rollback for this stage is limited to the EOF status-contract refinement and the S6 documentation/evidence additions:

- Revert the `end_of_file` mapping in `app/fall/status_contract.py`.
- Revert the shared reason mapping import/use in `app/services/status_service.py`.
- Revert the EOF assertions added to `tests/stabilization/test_unified_status_contract.py`.
- Remove this S6 report if the stage is re-run from a fresh evidence set.

Do not remove ignored local video assets, historical dirty files, or unrelated untracked files as part of rollback.

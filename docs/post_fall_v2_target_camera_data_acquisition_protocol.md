# Post-Fall V2 Target Camera Data Acquisition Protocol

Phase: `P2.5C_TARGET_CAMERA_DATA_ACQUISITION_AND_VALIDATION`

Status freeze:

- `POST_FALL_V2_ARCHITECTURE=CONFIRMED`
- `POST_FALL_V2_BINARY_ARTIFACT_CONTRACT=READY`
- `POST_FALL_V2_SHADOW_BINARY_ADAPTER=READY`
- `POST_FALL_V2_DOMAIN_TOOLCHAIN=READY`
- `POST_FALL_V2_DOMAIN_DATASET=BLOCKED`
- `POST_FALL_V2_THRESHOLD_TRANSFER=NOT_RUN`
- `POST_FALL_V2_BINARY_DOMAIN_VALIDATION=BLOCKED`
- `P3_ALLOWED=NO`

## Purpose

This phase is not algorithm development.

The only goal is to acquire reproducible `TARGET_CAMERA_REPLAY` videos from the current official elderly-care target camera, freeze the dataset and split, run the existing P2.5 replay/analysis tools, and decide whether EfficientNet-B0 is viable as the first-stage post-fall screening model.

Do not implement P3, VLM, incident, delivery, or alert code during this phase.

## Data Source Rule

Only this source can count as Domain Validation:

- `TARGET_CAMERA_REPLAY`: videos recorded by the same current target elderly-care camera that will be used in the real scene.

Do not count:

- mock video
- generated or synthetic media
- old fixtures
- Go2 training data
- internet images/videos
- footage from another camera

If RTSP is available, prefer recording short replay videos first, then run offline replay. Do not write RTSP credentials or full sensitive URLs into docs, JSON artifacts, logs, or Git-tracked files.

## Recording Plan

Recommended first batch:

- 24 to 30 recording sessions
- 10 to 20 seconds per session
- one stable posture/action per session
- 2 FPS shadow sampling target
- do not duplicate the same video to inflate counts

Priority scenarios:

| Scenario | Ground Truth | Target Sessions |
| --- | --- | ---: |
| `standing` | `noFall` | 2 |
| `sitting` | `noFall` | 2 |
| `bending` | `noFall` | 2 |
| `squatting` | `noFall` | 2 |
| `lying_bed` | `noFall` | 3 |
| `lying_sofa` | `noFall` | 3 |
| `lying_floor_normal` | `noFall` | 3 |
| `fallen_floor_supine` | `Fall` | 3 |
| `fallen_floor_side` | `Fall` | 3 |
| `fallen_floor_prone` | `Fall` | 3 |
| `partial_occlusion_fallen` | `Fall` | 2 |
| `no_person` | `noFall` | 1-2 |

If a scene is impossible in the test room, mark it `NOT_AVAILABLE_IN_TEST_ROOM`; do not substitute other-camera footage.

Most important six classes if time is tight:

- `fallen_floor_supine`
- `fallen_floor_side`
- `fallen_floor_prone`
- `lying_bed`
- `lying_sofa`
- `lying_floor_normal`

## Safety Rule

Fall scenarios are post-fall state tests. Nobody needs to perform a real dangerous fall.

Correct method:

1. The tester safely moves into the target floor posture.
2. The posture is stabilized.
3. Recording starts for the formal segment.
4. The segment begins with the person already in the post-fall state.

## Required Special Scenarios

`POST_FALL_BOOTSTRAP`:

- The person is already lying/fallen before the camera input begins.
- The clip contains no falling process.
- This validates whether V2 can detect an already occurred post-fall state.

`POST_FALL_RECONNECT`:

- Use replay construction where possible.
- Segment A has normal video.
- Input is interrupted.
- Segment B resumes with the person already fallen.
- Do not damage or disrupt real production equipment to create the interruption.

## Variables To Cover

Distance:

- `near`
- `medium`
- `far`

Critical case:

- `far + fallen_floor`

Lighting:

- `normal`
- `low`

Occlusion:

- `none`
- `partial`

If far-distance fallen recall collapses, mark `FULL_FRAME_DISTANCE_DEGRADATION` and do not unlock P3 before investigating FULL_FRAME 224 limitations.

## File Naming

Use:

```text
session_id__scenario__distance__lighting__occlusion.mp4
```

Examples:

```text
S001__standing__medium__normal__none.mp4
S002__lying_bed__medium__normal__none.mp4
S003__fallen_floor_side__near__normal__none.mp4
S004__fallen_floor_side__far__normal__none.mp4
S005__fallen_floor_side__medium__normal__partial.mp4
S006__post_fall_bootstrap__medium__normal__none.mp4
```

## Manifest Fields

Required or strongly recommended fields:

- `session_id`
- `camera_id`
- `camera_position_version`
- `room_id`
- `actor_id`
- `scenario_label`
- `binary_ground_truth`
- `split`
- `lighting`
- `distance`
- `occlusion`
- `source_type`
- `source_path`
- `recorded_at`
- `resolution`
- `source_width`
- `source_height`
- `sample_fps`
- `input_policy`
- `special_scenarios`

Use anonymous actor IDs such as `actor_01`; do not record real names.

## Split Freeze

Split by whole recording session:

- `DOMAIN_CALIBRATION`
- `DOMAIN_ACCEPTANCE`

Never split adjacent frames from the same video into both sets.

Freeze `domain_split_manifest.json` and its SHA256 before threshold analysis. Do not move sessions after seeing Acceptance results.

## First Analysis Rule

The first run must be Threshold Transfer only:

- model unchanged
- preprocessing unchanged: `FULL_FRAME_TRAIN_MATCHED`
- threshold unchanged: `0.3979087471961975`
- evaluate on frozen `DOMAIN_ACCEPTANCE`

Save the raw result even if it looks bad. Do not tune threshold before preserving the transfer result.

## Required Six Final Metrics

These six metrics must be reported independently:

1. `FALLEN_FLOOR_RECALL`
2. `LYING_BED_FPR`
3. `LYING_SOFA_FPR`
4. `LYING_FLOOR_NORMAL_FPR`
5. `FAR_DISTANCE_FALLEN_RECALL`
6. `POST_FALL_BOOTSTRAP_FIRST_HIT_SECONDS`

## P3 Unlock Rule

P3 may be unlocked only after target-camera evidence exists.

Allow `P3_ALLOWED=YES` if fallen-floor recall is stable and high, even if bed/sofa/normal-floor lying false positives are high. That would mean the binary model is useful as a high-recall screening layer and P3/P5 can be designed to reduce false positives.

Keep `P3_ALLOWED=NO` if far-distance fallen cases fail badly, or if fallen-floor recall is poor overall. In that case output:

```text
BINARY_SCREENING_NOT_DOMAIN_VIABLE
```

## Commands After Videos Are Ready

Use the existing template:

```powershell
.\.venv\Scripts\python.exe tools\run_post_fall_v2_domain_collection.py --write-template artifacts\post_fall_v2\domain_evidence\manifest_template.json
```

After filling the manifest with real replay paths:

```powershell
.\.venv\Scripts\python.exe tools\run_post_fall_v2_domain_collection.py --manifest path\to\domain_manifest.json
```

Then analyze the output run directory:

```powershell
.\.venv\Scripts\python.exe tools\analyze_post_fall_v2_domain_evidence.py --input artifacts\post_fall_v2\domain_evidence\<run_id>
```

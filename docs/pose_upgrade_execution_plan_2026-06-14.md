# Pose Upgrade Execution Plan

Generated: `2026-06-14`

## What Has Been Completed

- downloaded official ONNX SDK package for `RTMPose-X body7 384x288`
- extracted the ONNX model into:
  - [models/rtmpose/rtmpose-x-body7-384x288.onnx](/D:/Program/vision_service/models/rtmpose/rtmpose-x-body7-384x288.onnx)
- added a local ONNX-based pose estimator:
  - [app/pose/rtmpose_onnx_estimator.py](/D:/Program/vision_service/app/pose/rtmpose_onnx_estimator.py)
- wired `POSE_PROVIDER=rtmpose` and `POSE_PROVIDER=rtmpose_onnx` to the new provider path in:
  - [app/services/pose_service.py](/D:/Program/vision_service/app/services/pose_service.py)
- added pseudo-label export tooling:
  - [scripts/export_pose_pseudolabels.py](/D:/Program/vision_service/scripts/export_pose_pseudolabels.py)

## Why We Are Not Doing Full Supervised Fine-Tuning Immediately

Current repo evidence shows:

- there are many video-level labels for fall vs ADL
- there are temporal feature exports
- there is no ready-to-train body keypoint annotation dataset in repo-native format for this project

Therefore the most realistic project-specific adaptation path is:

1. replace the current runtime pose model
2. export high-quality pseudo-labels on your project videos
3. review and filter those pseudo-labels
4. build a project-specific pose adaptation set
5. only then run true supervised or semi-supervised fine-tuning

This is more honest and more aligned with the current project state than pretending a clean supervised pose training set already exists.

## Recommended Runtime Switch

Suggested env values:

```text
ENABLE_POSE=true
POSE_PROVIDER=rtmpose_onnx
RTMPOSE_ONNX_MODEL_PATH=models/rtmpose/rtmpose-x-body7-384x288.onnx
RTMPOSE_ONNX_INPUT_WIDTH=288
RTMPOSE_ONNX_INPUT_HEIGHT=384
RTMPOSE_DEVICE=cuda:0
POSE_FPS=3
POSE_WORKER_FPS=2
```

## Pseudo-Label Export Workflow

Example:

```powershell
python scripts/export_pose_pseudolabels.py `
  --video datasets\\gmdcsa24\\videos\\actor_1_fall_01.mp4 `
  --output data\\pose_pseudolabels\\actor_1_fall_01.jsonl `
  --frame-stride 3
```

Each row contains:

- frame index
- track id
- bbox
- pose keypoints
- pose confidence

## Adaptation Strategy

Phase 1:

- replace runtime model with RTMPose ONNX
- compare output quality against the current YOLO pose path

Phase 2:

- export pseudo-labels on project datasets:
  - `datasets/gmdcsa24`
  - `datasets/ur_fall`
  - any private field or dry-run videos you trust

Phase 3:

- manually review difficult scenes:
  - sitting near floor
  - bending
  - reclined but not fallen
  - occluded falls

Phase 4:

- create a curated pose adaptation dataset
- decide whether to fine-tune in:
  - OpenMMLab
  - MMDeploy-compatible workflow
  - pure ONNX export path after training

## Detailed Remaining Plan

### 1. Runtime replacement verification

Goal:

- switch the runtime from the old YOLO pose path to `rtmpose_onnx`
- confirm that tracked targets receive valid 17-keypoint outputs
- confirm that existing detection and tracking still work in the same environment

Concrete evidence:

- provider loads without error
- pseudo-label export succeeds on project videos
- pose payload contains valid keypoints and confidence scores

Status:

- provider load: completed
- sample pseudo-label export: completed
- full runtime switch and validation: still pending

### 2. Project-specific adaptation dataset generation

Goal:

- generate a COCO-style pseudo-labeled pose dataset from project videos

Practical source of videos:

- `data/phase7_labels/phase7_video_labels.jsonl` currently provides the most usable train/val/test balance
- it includes both `fall` and `non_fall`
- `phase9_video_manifest` is currently too fall-heavy for a balanced pose adaptation set

Evidence already collected:

- `phase7_video_labels.jsonl` usable rows: 250
- labels: 163 `fall`, 87 `non_fall`
- non-fall subtypes include sitting, bending, walking, standing, squatting, lying_down_normal

Status:

- export script prepared
- large-scale batch export still pending

### 3. Curated hard-case review

Goal:

- manually inspect the pseudo-labeled outputs for the scenes most likely to hurt fall classification

Priority cases:

- lying_down_normal
- sitting close to floor
- bending
- squatting
- partial occlusion
- low-light or blurred frames

Status:

- not started

### 4. Fine-tuning readiness

Goal:

- determine whether the pseudo-labeled adaptation set is good enough to justify supervised or semi-supervised pose fine-tuning

Current repo limitation:

- there is no ready project-native ground-truth keypoint annotation set

So the realistic deliverable now is:

- make the system fine-tuning-ready
- not falsely claim that a clean supervised fine-tune is already complete

## Current Best Practical Goal

The immediate realistic upgrade target is no longer “train a perfect new pose model from scratch”.

It is:

- switch the runtime to a stronger RTMPose ONNX body model
- generate project-specific pseudo-label assets
- use those assets to prepare a later targeted pose fine-tune

That is the most credible way to make the model more adapted to this project given the current repository evidence.

## Current Completion Status

Completed:

- target model research and narrowing
- official model download to local workspace
- local ONNX provider integration
- provider-side sample inference validation
- pseudo-label export on a sample project video
- COCO-style adaptation dataset export on a batch of project videos
- pose provider comparison on representative videos
- training-preparation manifest generation
- RTMPose adaptation config generation
- OpenMMLab training-stack import path investigation
- 3-epoch RTMPose adaptation fine-tune completed in `torchgpu`
- fine-tuned checkpoint smoke-loaded through the project `mmpose` provider
- three-way runtime comparison completed: `yolo` vs `rtmpose_onnx` vs `mmpose_finetuned`

Open risks still remaining:

- the fine-tune used pseudo-label adaptation data, not manually reviewed ground-truth keypoints
- this means the path is complete and runnable, but the resulting model should still be treated as a project-adapted candidate rather than a final certified production pose model

## Artifacts Produced

- Runtime model:
  - [models/rtmpose/rtmpose-x-body7-384x288.onnx](/D:/Program/vision_service/models/rtmpose/rtmpose-x-body7-384x288.onnx)
- Fine-tune init checkpoint:
  - [models/rtmpose/rtmpose-l-aic-coco-384x288.pth](/D:/Program/vision_service/models/rtmpose/rtmpose-l-aic-coco-384x288.pth)
- Fine-tuned best checkpoint:
  - [models/rtmpose/rtmpose-l-pose-adapted-best.pth](/D:/Program/vision_service/models/rtmpose/rtmpose-l-pose-adapted-best.pth)
- Sample pseudo-label export:
  - [data/pose_pseudolabels/actor_1_fall_01.jsonl](/D:/Program/vision_service/data/pose_pseudolabels/actor_1_fall_01.jsonl)
- Full adaptation dataset:
  - [data/pose_adaptation_dataset_full](/D:/Program/vision_service/data/pose_adaptation_dataset_full)
- Provider comparison:
  - [evaluations/phase10_pose_provider_comparison_001.json](/D:/Program/vision_service/evaluations/phase10_pose_provider_comparison_001.json)
- Training preparation manifest:
  - [evaluations/phase10_pose_adaptation_training_plan_001.json](/D:/Program/vision_service/evaluations/phase10_pose_adaptation_training_plan_001.json)
- Training config stub:
  - [models/rtmpose/rtmpose_l_pose_adaptation_384x288.py](/D:/Program/vision_service/models/rtmpose/rtmpose_l_pose_adaptation_384x288.py)

# Pose Model Upgrade Research

Generated: `2026-06-14`

## Goal

Replace the current pose model path with a stronger, modern model that is close
to the quality tier you expect from a frontier YOLO26 Pose-class solution, while
still fitting this repo's real-time architecture.

Current architecture constraints from code:

- detection/tracking already produces person bounding boxes
- pose runs as a single-person refinement step on tracked targets
- downstream logic expects COCO-style 17 keypoints
- runtime cares about inference latency and stability
- pose results feed temporal fall logic and behavior rules

These constraints make top-down pose models especially attractive.

## Shortlist

### 1. RTMPose-L

Why it fits:

- state-of-the-art practical top-down pose model family from OpenMMLab
- designed for real-time or near-real-time deployment
- strong COCO keypoint quality
- natural fit for this repo because tracked person boxes already exist
- stable Python inference path through `mmpose`

Integration fit:

- excellent
- minimal downstream schema change
- no need to rewrite temporal feature extraction

Recommendation:

- `RTMPose-L 384x288` is the best primary upgrade target

Official browser-validated evidence:

- MMPose official model zoo reports `rtmpose-l-aic-coco 384x288` at `0.773 AP` on COCO val2017 with a detector that has human AP `56.4`
- MMPose official model zoo reports `rtmpose-l 256x192` at `0.758 AP`

Source:

- [MMPose body 2D keypoint model zoo](https://mmpose.readthedocs.io/en/latest/model_zoo/body_2d_keypoint.html)

### 2. RTMO-L

Why it is interesting:

- newer one-stage real-time pose direction from OpenMMLab
- stronger “frontier” feel than older YOLO pose baselines

Why it is not the first replacement here:

- this repo already has person detection plus tracking
- replacing only pose is easier and lower-risk than replacing the whole person-to-pose stage
- RTMO is more attractive when you want to rethink the detection+pose stack together

Recommendation:

- keep as phase-2 option after RTMPose proves stable

Official browser-validated evidence:

- MMPose official model zoo reports `RTMO-l 640x640` at `0.724 AP` on COCO val2017
- The same official page reports `RTMO-l 640x640` at `0.732 AP` on CrowdPose test

Sources:

- [MMPose body 2D keypoint model zoo](https://mmpose.readthedocs.io/en/latest/model_zoo/body_2d_keypoint.html)
- [RTMO CVPR 2024 paper page](https://openaccess.thecvf.com/content/CVPR2024/html/Lu_RTMO_Towards_High-Performance_One-Stage_Real-Time_Multi-Person_Pose_Estimation_CVPR_2024_paper.html)

### 3. DWPose

Why it is strong:

- strong quality and widely used in motion/animation/control ecosystems

Why it is weaker as the first upgrade here:

- less aligned with this repo's simple COCO-17 fall-analysis path
- often chosen for richer control/body quality rather than the cleanest realtime fall-pipeline replacement

Recommendation:

- not first choice for this project

Official browser-validated evidence:

- DWPose official repo reports on COCO-WholeBody v1.0 val:
  - `DWPose-l 256x192`: `Body AP 0.704`, `Whole AP 0.631`
  - `DWPose-l 384x288`: `Body AP 0.722`, `Whole AP 0.665`
- The official repo emphasizes ONNX-based inference and ControlNet-style usage

Source:

- [DWPose official repository](https://github.com/IDEA-Research/DWPose)

### 4. Continue with newer YOLO pose weights

Why it is tempting:

- lowest migration cost

Why it is not enough:

- user pain is already with the current YOLO-family path
- quality ceiling is less convincing than RTMPose for this exact tracked-person refinement problem

Recommendation:

- keep as baseline only, not as main upgrade path

Official browser-validated evidence:

- Ultralytics official pose documentation reports:
  - `YOLO26l-pose`: `70.4` mAP pose 50-95
  - `YOLO26x-pose`: `71.6` mAP pose 50-95

Source:

- [Ultralytics pose task documentation](https://docs.ultralytics.com/tasks/pose/)

### 5. ViTPose / Sapiens

Why they matter:

- both are strong high-end references for current pose quality
- both show what “frontier” quality looks like beyond lightweight YOLO-family pose models

Why they are not the first practical replacement here:

- `ViTPose` is a stronger research-style accuracy route, but heavier than what this realtime fall pipeline needs first
- `Sapiens` is even more ambitious and general, but its official setup and checkpoint stack are much heavier than an incremental provider swap

Official browser-validated evidence:

- ViTPose official repo states `81.1 AP` on the MS COCO Keypoint test-dev set
- Sapiens official repo describes a family pretrained on `300 million` in-the-wild human images and trained at `1024x1024` resolution for human-centric tasks including 2D pose

Sources:

- [ViTPose official repository](https://github.com/ViTAE-Transformer/ViTPose)
- [Sapiens official repository](https://github.com/facebookresearch/sapiens)
- [Sapiens2 official repository](https://github.com/facebookresearch/sapiens2)

### 6. RTMW

Why it matters:

- a newer OpenMMLab real-time whole-body direction
- stronger than older whole-body baselines
- useful if your future roadmap expands from 17 body keypoints to full whole-body reasoning

Why it is not the first replacement here:

- your current temporal fall pipeline consumes COCO-17 body keypoints
- RTMW is more attractive when you want whole-body, face, hand, and foot reasoning together
- migration cost is higher than swapping in RTMPose for the current body-pose stage

Official browser-validated evidence:

- MMPose whole-body model zoo reports on Cocktail14 / COCO-WholeBody style evaluation:
  - `rtmw-l 384x288`: `Whole AP 0.701`
  - `rtmw-x 384x288`: `Whole AP 0.702`

Source:

- [MMPose wholebody 2D keypoint model zoo](https://mmpose.readthedocs.io/en/latest/model_zoo/wholebody_2d_keypoint.html)

## Final Recommendation

Primary recommendation:

- adopt `RTMPose-L` as the new high-quality pose provider

Practical deployment recommendation:

- prefer `RTMPose-L` as the model family decision
- consider two implementation paths:
  1. direct OpenMMLab path through `mmpose`
  2. lighter ONNX path through `rtmlib` when you want lower integration weight

The lighter `rtmlib` path is especially attractive for this repo because it may
preserve most of the current service structure while avoiding the heavier
`mmcv/mmengine/mmdet/mmpose` runtime stack.

Official browser-validated evidence for the lighter path:

- `rtmlib` official repo describes itself as a lightweight library for `RTMPose`
  and `ViTPose` without `mmcv`, `mmpose`, `mmdet`
- listed core dependencies are only `numpy`, `opencv-python`,
  `opencv-contrib-python`, and `onnxruntime`

Source:

- [rtmlib official repository](https://github.com/Tau-J/rtmlib)

Important browser-validated implementation detail:

- the `rtmlib` README shows a `Custom` path that separately configures detector and
  pose estimator weights
- the sample pose URL points to OpenMMLab official download assets under
  `download.openmmlab.com/.../onnx_sdk/...`
- this makes `rtmlib` a practical bridge between official RTMPose-family weights
  and a lighter service integration
- `rtmlib` explicitly lists support for:
  - `RTMPose for 17 keypoints`
  - `RTMO for 17 keypoints`
  - `RTMW for 133 keypoints`
  - `DWPose for 133 keypoints`
  - `ViTPose for 17 keypoints`

Implication for this repo:

- if we want the fastest path to replacing the current pose module without
  pulling in the full OpenMMLab runtime stack, `rtmlib` is now a serious first-class option
- the presence of a dedicated `RTMPose for 17 keypoints` path is especially
  aligned with this repo's current temporal fall-analysis assumptions

Evidence-based ranking for *this* repo:

1. `RTMPose-L 384x288`
   - best balance of quality, maturity, and direct fit to the existing top-down tracked-person pipeline
2. `RTMO-L`
   - best alternative when you want a more radical one-stage pose refresh later
3. `YOLO26x-pose`
   - useful baseline and easy to deploy, but not the best upgrade if the current YOLO-family pose path already disappoints
4. `RTMW-l/x`
   - strong whole-body direction, but too broad for the first body-only fall-pipeline replacement
5. `ViTPose`
   - stronger heavyweight research baseline than a practical first replacement here
6. `Sapiens / Sapiens2`
   - most ambitious general human-vision direction, but too heavy for the first migration step

## Architecture Choice Summary

From the browser-validated comparison material:

- `RTMPose`
  - top-down
  - best fit when you already have person detection and tracking
- `RTMO`
  - one-stage
  - more attractive when you want to remove the detector+pose split
- `RTMW`
  - whole-body extension of the RTM line
  - better when face, hand, foot, and 3D reasoning become project requirements
- `DWPose`
  - distilled whole-body line
  - attractive for whole-body and ONNX-centric use cases, but less aligned with the current 17-point fall pipeline

Useful browser-validated comparison reference:

- [MMPose discussion 3135](https://github.com/open-mmlab/mmpose/discussions/3135)

## License And Weight Risk Notes

Browser-based research surfaced an important caution:

- repository license and model-weight training-data license are not always the same

Strong browser-validated evidence:

- `rtmlib` maintainer states the repository and the RTMPose series of models
  follow Apache-2.0 and can be used commercially with attribution
- a follow-up comment correctly points out that some pretrained weights may
  inherit restrictions from datasets such as COCO-WholeBody

Implication:

- for production/commercial deployment, prefer RTMPose body-only checkpoints
  whose lineage is easiest to justify
- avoid assuming that every “AIC-COCO”, “Halpe”, or whole-body variant is equally
  clean for commercial use without an extra dataset-license review

Source:

- [rtmlib issue 65: commercial use](https://github.com/Tau-J/rtmlib/issues/65)

## Current Best Engineering Route

After browser-based research across official docs, official repos, and the
lightweight deployment ecosystem, the strongest practical recommendation is now:

1. choose `RTMPose-L 384x288` as the target model family
2. evaluate `rtmlib` first as the integration vehicle
3. keep direct `mmpose` integration as fallback if we need closer parity with
   official Python APIs or more configuration control

Why this route is strongest:

- best fit for the repo's existing detection + tracking + top-down pose shape
- higher public accuracy than the current YOLO-family pose route
- lighter deployment path is available
- lower migration risk than one-stage or whole-body-first alternatives

## Concrete Replacement Target

The most practical concrete target to replace the current pose module is:

- `RTMPose Body (17 keypoints)`
- preferred quality tier: `L`
- preferred resolution tier when latency allows: `384x288`

Why this specific target is best:

- this repo's temporal fall logic is currently built around COCO-style body keypoints
- `rtmlib` explicitly separates:
  - `Body` for 17 keypoints
  - `Body_with_feet` / whole-body routes for richer schemas
- choosing the plain body route minimizes downstream schema churn

Current checkpoint guidance from research:

1. highest-performing currently identified body checkpoint:
   - `rtmpose-l-aic-coco 384x288`
2. most conservative lineage choice for production review:
   - plain COCO-lineage `rtmpose-l 256x192` or another body-only checkpoint

Engineering implication:

- for pure technical quality evaluation, start from the strongest `L`-tier body checkpoint
- for production/commercial review, do a stricter checkpoint-by-checkpoint dataset provenance pass before freezing the runtime default

## Browser-Validated rtmlib Body Mode Mapping

`rtmlib` exposes a very practical mapping for the 17-keypoint body route:

- `performance`
  - detector: `yolox_x`
  - pose: `rtmpose-x_simcc-body7_pt-body7_700e-384x288`
- `balanced`
  - detector: `yolox_m`
  - pose: `rtmpose-m_simcc-body7_pt-body7_420e-256x192`
- `lightweight`
  - detector: `yolox_tiny`
  - pose: `rtmpose-s_simcc-body7_pt-body7_420e-256x192`

Important implication:

- if we follow `rtmlib`'s built-in `Body` route, the strongest ready-made body
  option is currently the `performance` mode using `RTMPose-X 384x288`
- this means the practical `rtmlib` recommendation is slightly different from
  the earlier broad MMPose-family recommendation of `RTMPose-L`

Updated engineering reading:

- for direct `mmpose` integration, `RTMPose-L` remains the clean primary target
- for lightweight ONNX integration through `rtmlib`, `RTMPose-X 384x288` becomes
  the strongest out-of-the-box body replacement candidate

Additional browser-validated deployment evidence:

- OpenMMLab's RTMPose deployment article reports:
  - `RTMPose-m` reaches `90+ FPS` on Intel i7-11700 CPU using ONNXRuntime
  - `RTMPose-m` reaches `430+ FPS` on NVIDIA GTX 1660 Ti using TensorRT
  - `RTMPose-s` reaches `70+ FPS` on Snapdragon 865 using ncnn

Implication:

- even if exact `RTMPose-X body7 384x288` speed is not published in the same
  simple table, the RTMPose family is clearly designed for practical deployment
- this strengthens confidence that a body-only RTMPose replacement is aligned
  with this repo's real-time service goals

Source:

- [OpenMMLab RTMPose article](https://openmmlab.medium.com/rtmpose-the-all-in-one-real-time-pose-estimation-solution-for-application-and-research-6404f17cd52f)

Practical rollout strategy:

1. Keep current `POSE_PROVIDER=yolo` as fallback
2. Add `POSE_PROVIDER=rtmpose`
3. Benchmark on your real camera scenes and failure cases
4. If latency is acceptable, switch runtime default to `rtmpose`
5. If you later want a larger architectural refresh, evaluate `RTMO-L`

## Why RTMPose Wins For This Repo

This repo does not need a new end-to-end person detector. It already has:

- YOLO person detection
- ByteTrack tracking
- target selection
- temporal fall reasoning

The weak point is the quality of single-person pose estimation after tracking.
That is exactly where RTMPose is strong.

So the best upgrade is not “replace everything with a fashionable model”, but:

- keep the existing detection/tracking pipeline
- replace only the pose estimation stage with a stronger top-down model

This gives the highest quality gain for the lowest integration risk.

## Code Progress In This Repo

This repo now includes:

- new provider name: `POSE_PROVIDER=rtmpose`
- new estimator: [app/pose/rtmpose_estimator.py](/D:/Program/vision_service/app/pose/rtmpose_estimator.py)
- provider selection wiring in [app/services/pose_service.py](/D:/Program/vision_service/app/services/pose_service.py)
- config fields in [app/core/config.py](/D:/Program/vision_service/app/core/config.py)
- env template updates in [.env.example](/D:/Program/vision_service/.env.example)

This is integration scaffolding, not a fully verified model installation yet.

## Required Runtime Assets

Expected local files:

```text
models/rtmpose/rtmpose-l_8xb256-420e_coco-384x288.py
models/rtmpose/rtmpose-l_simcc-coco_pt-aic-coco_420e-384x288-9ec0a4e5_20230127.pth
```

Expected Python dependencies:

```text
openmim
mmengine
mmcv
mmdet
mmpose
```

## Suggested Runtime Config

```text
ENABLE_POSE=true
POSE_PROVIDER=rtmpose
POSE_FPS=3
RTMPOSE_CONFIG_PATH=models/rtmpose/rtmpose-l_8xb256-420e_coco-384x288.py
RTMPOSE_CHECKPOINT_PATH=models/rtmpose/rtmpose-l_simcc-coco_pt-aic-coco_420e-384x288-9ec0a4e5_20230127.pth
RTMPOSE_DEVICE=cuda:0
RTMPOSE_BBOX_THR=0.2
```

## Verification Plan

Before declaring the upgrade complete, verify:

1. model loads successfully in runtime status
2. pose keypoints are produced on real tracked targets
3. latency stays within acceptable bounds
4. no regression in temporal fall pipeline
5. current failure cases improve compared with the YOLO pose provider

## External Research Notes

Research sources were checked from primary project/documentation paths:

- Ultralytics pose task documentation
- OpenMMLab MMPose inference and project documentation
- official project repositories for RTMPose / RTMO / DWPose

The final recommendation here is an engineering fit judgment based on those
primary sources plus this repo's actual architecture.

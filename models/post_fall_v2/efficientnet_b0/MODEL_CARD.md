# Post-Fall V2 EfficientNet-B0 Binary Candidate

Status: audit/shadow candidate only. This asset is not connected to Runtime.

## Identity

- Architecture: `efficientnet_b0`
- Task: binary Fall/noFall image classification
- Classes: `noFall=0`, `Fall=1`
- Positive score: `fall_probability = softmax(logits)[1]`
- ONNX: `fall_candidate_efficientnet_b0.onnx`
- Checkpoint: `best_model.pth`

## Hashes

- ONNX SHA256:
  `e9871cdb4687055fb5d934dd994c2ad883adac0c2acab375c240f8e005ee04cc`
- Checkpoint SHA256:
  `e2c2cf6f2cd6324ad9199bdb32922d11e3638ed81d218adbc5033c6e98cb5b94`

## Input Contract

- Semantic input: full camera frame, not a YOLO person crop.
- Tensor input: `float32 NCHW`, dynamic batch, `3x224x224`.
- Preprocessing:
  `RGB -> LongestMaxSize(224) -> center PadIfNeeded(224,224, BORDER_REFLECT_101) -> ImageNet Normalize -> ToTensor`.
- Mean: `(0.485, 0.456, 0.406)`
- Std: `(0.229, 0.224, 0.225)`

## Output Contract

- ONNX input name: `input`
- ONNX output name: `logits`
- ONNX output shape: `[batch, 2]`
- Apply softmax and take index `1` as `fall_probability`.

## Threshold

- Candidate threshold name: `BINARY_CANDIDATE_THRESHOLD_OOF`
- Value: `0.3979087471961975`
- Evidence source: group-held-out OOF model selection on 185 development images.
- This is not a production fall-alert threshold.

## Dataset Evidence

- Total images: `185`
- Fall: `64`
- noFall: `121`
- Split counts:
  - train: Fall `26`, noFall `49`
  - val: Fall `22`, noFall `42`
  - test: Fall `16`, noFall `30`
- Group split is leakage-free by recording group.

## Gates

- Artifact contract: `POST_FALL_V2_BINARY_ARTIFACT_CONTRACT_READY`
- Domain validation: `POST_FALL_V2_BINARY_DOMAIN_VALIDATION_BLOCKED`

Allowed next stage: `P2_SHADOW_FRAME_AND_BINARY_ADAPTER`.

Forbidden until later approval: active Runtime integration, `.env` changes, VLM enablement, external delivery, production-ready claims.

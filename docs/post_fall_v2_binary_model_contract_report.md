# Post-Fall V2 Binary Model Contract Report

Stage: `P1_POST_FALL_BINARY_MODEL_CONTRACT_VERIFICATION`

Date: 2026-08-10

Scope: standalone model-contract verification only. This stage does not connect
Post-Fall V2 into Runtime and does not change the active legacy pipeline.

Final gate: `POST_FALL_V2_BINARY_CONTRACT_BLOCKED`

## 1. Executive Summary

The candidate binary classifier can be loaded and executed with the local
Ultralytics runtime. Its actual task is classification, not detection.

Verified:

- `MODEL_LOAD_VERIFIED`: yes.
- `PREPROCESS_VERIFIED`: yes for the Ultralytics image transform embedded in
  the `.pt` file and used by `YOLO.predict`.
- `CLASS_MAPPING_VERIFIED`: yes at the model-native level: index `0` is `risk`,
  index `1` is `safe`.
- `REAL_INFERENCE_VERIFIED`: yes on CPU against real local images.

Still blocked for V2 product use:

- `THRESHOLD_EVIDENCE_NOT_REPO_CONTROLLED`: the usable VAL/TEST data and
  training run artifacts are under `D:/Program/model/fall_detection`, not inside
  this project.
- `DATASET_SEMANTIC_GAP`: labels are only `risk/safe`, derived from posture
  classes. There is no explicit held-out semantic split for floor fall vs normal
  lying on bed/sofa/exercise/intentional floor activity.
- `FRAME_TO_PERSON_CROP_POLICY_NEEDS_FREEZE`: evidence indicates the classifier
  expects person crops, not raw full frames. Future V2 integration must define
  how a frame becomes a crop before calling the classifier.

## 2. Model Identity

Formal candidate in current project:

`models/showcase_assets/health1_demo/yolo_posture_person_binary_cls_best.pt`

External original referenced by historical code:

`D:/Program/model/fall_detection/runs/yolo_posture_person_binary_cls_v1/weights/best.pt`

External registry evidence:

`D:/Program/model/fall_detection/configs/model_registry.yaml`

```yaml
posture_risk:
  type: classify
  framework: ultralytics
  path: runs/yolo_posture_person_binary_cls_v1/weights/best.pt
  imgsz: 384
```

## 3. Model Hash

SHA256:

`a5300114188aa6ef95ff5b5d0e08af124f5670cb927dc91b42f10e94da825bf1`

Model size:

`11,023,362 bytes`

## 4. Framework / Task

Runtime verification command loaded the model through `ultralytics.YOLO`.

Observed values:

- Ultralytics version: `8.4.117`
- Torch version: `2.13.0+cpu`
- CUDA available: `false`
- Framework: `ultralytics`
- Model type: `ClassificationModel`
- Task: `classify`
- Metadata names: `{0: "risk", 1: "safe"}`
- Metadata `imgsz`: `384`

This is not inferred from the filename. It was verified from the loaded model
object and checkpoint metadata.

## 5. Training Artifact Evidence

External training run:

`D:/Program/model/fall_detection/runs/yolo_posture_person_binary_cls_v1`

Found artifacts:

- `args.yaml`
- `results.csv`
- `confusion_matrix.png`
- `confusion_matrix_normalized.png`
- `results.png`
- `weights/best.pt`
- `weights/last.pt`
- train/val batch visualization images

Relevant `args.yaml` values:

- `task: classify`
- `model: yolo11s-cls.pt`
- `data: D:\Program\model\fall_detection\data_processed\fallpose_person_binary_cls`
- `epochs: 25`
- `batch: 48`
- `imgsz: 384`
- `split: val`
- `crop_fraction: 1.0`
- `bgr: 0.0`
- `val: true`

Dataset builder evidence:

`D:/Program/model/fall_detection/scripts/build_fallpose_person_binary_cls_dataset.py`

It maps posture classes as:

- `lying`, `crawling`, `bending` -> `risk`
- `standing`, `sitting` -> `safe`

This means `risk` is a static posture-risk class, not a complete confirmed fall
incident label.

## 6. Input Contract

Verified model-level input:

- Input source type: image/crop accepted by `ultralytics.YOLO.predict`.
- Expected semantic content: person crop / posture crop.
- Input size after transforms: `3 x 384 x 384`.
- Batch dimension: added by Ultralytics predictor.
- Device tested: CPU.

Important boundary:

The model should not be treated as a verified raw full-frame classifier. External
historical scripts use person crops:

- `extract_posture_risk_cache.py` crops a person box with margin `0.12`.
- `realtime_fall_monitor.py` crops `frame[y1:y2, x1:x2]` from a tracked person
  box before calling `classify_posture`.

The future V2 adapter must explicitly define the frame-to-person-crop policy.

## 7. Preprocessing Contract

Verified embedded transforms from `model.model.transforms`:

```text
Resize(size=384, interpolation=bilinear, antialias=True)
CenterCrop(size=(384, 384))
ToTensor()
Normalize(mean=[0,0,0], std=[1,1,1])
```

Verified Ultralytics predictor behavior:

- OpenCV-loaded BGR image is converted to RGB before PIL transforms.
- PIL/torchvision pipeline handles resize and center crop.
- `ToTensor()` converts HWC uint8 to CHW float and scales values to `[0,1]`.
- `Normalize(mean=0, std=1)` performs no ImageNet mean/std normalization.
- Letterbox is not used for this classification `.pt` path.

Preprocess status:

`TRAIN_INFER_PREPROCESS_MATCH` for the Ultralytics model transform path.

Scoped caveat:

The outer crop policy is not frozen. Training data appears to be person-crop
posture images, while historical runtime scripts differ on crop margin.

## 8. Output Contract

High-level API output:

- `YOLO.predict(...)[0].probs`
- `probs.data`: probability vector ordered by `model.names`
- `probs.top1`: top class index
- `probs.top1conf`: top class probability
- `probs.top5` / `probs.top5conf`: ranked classes/probabilities

Manual forward probe showed the classification model returns a tuple containing:

- part `0`: probabilities, sum approximately `1.0`
- part `1`: logits

The standalone verifier records `Results.probs` because that is the stable public
Ultralytics inference output used by existing scripts.

## 9. Class Mapping

Model-native mapping:

| Index | Name |
| ----: | ---- |
| 0 | `risk` |
| 1 | `safe` |

V2 candidate score definition for this stage:

```text
fall_probability = probability assigned to class index 0 ("risk")
```

This value is a first-stage posture-risk score only. It is not a final fall
incident probability and must not directly trigger an alert.

## 10. Inference Example

Standalone verifier:

`tools/verify_post_fall_binary_model.py`

Safe sample:

- Source:
  `D:/Program/model/fall_detection/data_processed/fallpose_person_binary_cls/test/safe/1843_0001.png`
- Prediction: `safe`
- `fall_probability`: `0.006443`
- JSON:
  `artifacts/post_fall_v2_binary_contract_safe_smoke.json`

Risk sample:

- Source:
  `D:/Program/model/fall_detection/data_processed/fallpose_person_binary_cls/test/risk/1843_0439.png`
- Prediction: `safe`
- `fall_probability`: `0.013193`
- JSON:
  `artifacts/post_fall_v2_binary_contract_risk_smoke.json`

The risk-sample miss is useful evidence: this classifier cannot be accepted by
single-image smoke success. It requires threshold sweeps and scenario validation.

## 11. Dataset Evidence

External dataset path from model metadata:

`D:/Program/model/fall_detection/data_processed/fallpose_person_binary_cls`

Observed split counts:

| Split | Risk | Safe | Total |
| ---- | ---: | ---: | ----: |
| TRAIN | 1559 | 1870 | 3429 |
| VAL | 710 | 1473 | 2183 |
| TEST | 918 | 2352 | 3270 |

Validation category:

- `TRAIN`: not used for threshold sweep.
- `VAL`: used for threshold sweep.
- `TEST`: used for threshold sweep.
- `DEMO`: single-image smoke examples only.
- `SYNTHETIC`: not used.
- `REPLAY`: not used.
- `LIVE`: not used.

Repo-control status:

`VALIDATION_DATASET_NOT_REPO_CONTROLLED`

The data is real and readable on this machine, but it is outside the current
project tree. It should be promoted or mirrored with manifests before being used
as a frozen product threshold basis.

## 12. Threshold Sweep

VAL sweep selected rows:

| Threshold | TP | FP | TN | FN | Precision | Recall | F1 | FPR |
| --------: | -: | -: | -: | -: | --------: | -----: | -: | --: |
| 0.05 | 686 | 642 | 831 | 24 | 0.516566 | 0.966197 | 0.673209 | 0.435845 |
| 0.10 | 654 | 407 | 1066 | 56 | 0.616400 | 0.921127 | 0.738566 | 0.276307 |
| 0.40 | 573 | 144 | 1329 | 137 | 0.799163 | 0.807042 | 0.803083 | 0.097760 |
| 0.50 | 560 | 111 | 1362 | 150 | 0.834575 | 0.788732 | 0.811007 | 0.075356 |
| 0.65 | 544 | 81 | 1392 | 166 | 0.870400 | 0.766197 | 0.814981 | 0.054990 |
| 0.70 | 536 | 76 | 1397 | 174 | 0.875817 | 0.754930 | 0.810893 | 0.051595 |
| 0.80 | 518 | 63 | 1410 | 192 | 0.891566 | 0.729577 | 0.802479 | 0.042770 |
| 0.95 | 442 | 37 | 1436 | 268 | 0.922756 | 0.622535 | 0.743482 | 0.025119 |

TEST sweep selected rows:

| Threshold | TP | FP | TN | FN | Precision | Recall | F1 | FPR |
| --------: | -: | -: | -: | -: | --------: | -----: | -: | --: |
| 0.05 | 888 | 1591 | 761 | 30 | 0.358209 | 0.967320 | 0.522814 | 0.676446 |
| 0.10 | 845 | 1174 | 1178 | 73 | 0.418524 | 0.920479 | 0.575417 | 0.499150 |
| 0.40 | 730 | 484 | 1868 | 188 | 0.601318 | 0.795207 | 0.684803 | 0.205782 |
| 0.50 | 711 | 386 | 1966 | 207 | 0.648131 | 0.774510 | 0.705707 | 0.164116 |
| 0.65 | 672 | 273 | 2079 | 246 | 0.711111 | 0.732026 | 0.721417 | 0.116071 |
| 0.70 | 659 | 245 | 2107 | 259 | 0.728982 | 0.717865 | 0.723381 | 0.104167 |
| 0.80 | 599 | 198 | 2154 | 319 | 0.751568 | 0.652505 | 0.698542 | 0.084184 |
| 0.95 | 465 | 120 | 2232 | 453 | 0.794872 | 0.506536 | 0.618762 | 0.051020 |

Full artifacts:

- `artifacts/post_fall_v2_binary_contract_val_sweep.json`
- `artifacts/post_fall_v2_binary_contract_val_records.csv`
- `artifacts/post_fall_v2_binary_contract_test_sweep.json`
- `artifacts/post_fall_v2_binary_contract_test_records.csv`

## 13. Recommended Candidate Operating Points

These are not product thresholds. They are evidence-backed operating points for
the next offline/shadow evaluation only.

VAL:

- Best F1: threshold `0.65`, F1 `0.814981`, recall `0.766197`,
  precision `0.870400`.
- High recall: threshold `0.05`, recall `0.966197`, but FPR `0.435845`.
- Balanced precision/recall: threshold `0.40`, precision `0.799163`,
  recall `0.807042`.

TEST:

- Best F1: threshold `0.70`, F1 `0.723381`, recall `0.717865`,
  precision `0.728982`.
- High recall: threshold `0.05`, recall `0.967320`, but FPR `0.676446`.
- Balanced precision/recall: threshold `0.70`, precision `0.728982`,
  recall `0.717865`.

Recommendation:

Do not freeze a product threshold yet. Use `0.65` and `0.70` as shadow-mode
comparison points after the validation artifacts are brought under repo control
and after semantic hard-negative evaluation is added.

## 14. Fall / Normal-Lying Risk Analysis

The binary labels are posture-derived:

- risk = `lying`, `crawling`, `bending`
- safe = `standing`, `sitting`

This is not enough to answer the core Post-Fall V2 distinction:

```text
fallen on floor
vs
normal lying on bed or sofa
```

The current classifier may be useful as a first-stage low-posture/risk screener,
but it is not yet a reliable "already fallen" discriminator.

## 15. Dataset Semantic Gaps

Current blocker:

`DATASET_SEMANTIC_GAP`

The available labels do not provide explicit scenario strata for:

- fallen on floor
- normal lying on bed
- lying on sofa
- sitting
- squatting
- bending
- person on floor intentionally
- exercise
- occlusion
- far distance
- night / low light
- multiple persons

Some of these may be present visually, but they are not encoded in the
`risk/safe` labels or in a repo-controlled manifest. They cannot be audited or
swept independently yet.

## 16. BinaryFallResult Schema

Proposed interface for future V2 service boundary:

```python
BinaryFallResult = {
    "frame_id": str,
    "camera_id": str | None,
    "timestamp": str | None,
    "prediction": str,
    "fall_probability": float | None,
    "class_index": int | None,
    "model_name": str,
    "model_version": str | None,
    "model_hash": str,
    "inference_ms": float | None,
    "input_width": int | None,
    "input_height": int | None,
    "valid": bool,
    "error_code": str | None,
}
```

The standalone tool also records source/model paths, input shape,
preprocessing summary, and raw output summary for auditability.

## 17. Tests

Added tests:

`tests/test_verify_post_fall_binary_model.py`

Coverage:

- missing image
- unsupported input
- invalid source combination
- directory image filtering
- risk/safe class mapping
- threshold metrics
- JSON serialization

Executed:

```text
.\.venv\Scripts\python.exe -m pytest tests\test_verify_post_fall_binary_model.py -q
```

Result:

```text
6 passed
```

Runtime verification:

- CPU inference: verified.
- CUDA inference: not run because `torch.cuda.is_available()` returned `false`.

## 18. Known Risks

- The `.pt` contract is tied to Ultralytics classification transforms. Exported
  formats must be separately verified.
- Existing scripts disagree on outer crop margin. This can shift score
  distributions.
- The classifier detects posture risk, not a fall event.
- TEST performance is materially weaker than VAL at the same thresholds.
- The high-recall point produces unacceptable false-positive rates if used
  alone.
- Current dataset labels cannot isolate bed/sofa lying from dangerous floor
  lying.

## 19. Blocked Items

Blocking items before `POST_FALL_V2_BINARY_CONTRACT_READY`:

- `THRESHOLD_EVIDENCE_NOT_REPO_CONTROLLED`
- `DATASET_SEMANTIC_GAP`
- `FRAME_TO_PERSON_CROP_POLICY_NEEDS_FREEZE`
- `PRODUCT_THRESHOLD_NOT_APPROVED`

Not blocked:

- Building a standalone shadow adapter around this model.
- Designing `BinaryFallResult`.
- Running replay/shadow experiments with candidate thresholds.

## 20. Next Allowed Stage

Allowed next step:

`P2_FRAME_SAMPLER_AND_BINARY_ADAPTER_SHADOW`

Conditions:

- Do not connect to Runtime main chain yet.
- Do not modify `.env`.
- Do not change `pipeline_mode=legacy`.
- Do not enable VLM or external delivery.
- Add an explicit frame-to-person-crop policy.
- Run the classifier in offline/shadow mode only.
- Promote or reference validation artifacts with reproducible manifests.
- Add semantic hard-negative sets before any product threshold is frozen.

Final decision:

`POST_FALL_V2_BINARY_CONTRACT_BLOCKED`

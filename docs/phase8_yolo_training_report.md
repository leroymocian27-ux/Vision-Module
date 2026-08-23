# Phase 8 YOLO Deep Training Report

Generated: 2026-06-08T03:10:05.076696+00:00

## Data Download And Access

- Data hub: D:\Program\数据集
- Kaggle credentials present: False
- Roboflow API key present: False
- GitHub metadata repository downloaded via codeload master zip.
- Ultralytics base models downloaded: yolo11s.pt, yolo11m.pt.

## Dataset Gate

- UR Fall official: status=available_via_existing_link, usable=True, license=CC BY-NC-SA 4.0
- Le2i / ImViA Fall Dataset: status=blocked_no_kaggle_credentials, usable=False, license=Kaggle dataset license must be accepted by user
- Roboflow UR Fall YOLO export: status=blocked_no_roboflow_api_key, usable=False, license=per-project Roboflow Universe license
- FPDS: status=blocked_manual_authorization, usable=False, license=official terms must be checked before training
- YifeiYang210 Fall Detection dataset metadata: status=pending, usable=False, license=GitHub repository terms; linked data license must be checked

## Training Data

- fall_detect_existing: images=2840, labels=2840
- fall_detect_v2_recall_existing: images=7932, labels=7932
- fall_detect_v3_gmdcsa24_autolabel: images=1246, labels=1246

## YOLO v5 Training

- base model: D:\Program\数据集\downloaded_models\ultralytics\yolo11s.pt
- completed epochs: 12
- imgsz: 768
- best weight: D:\Program\vision_service\models\yolo_fall_detector_v5_best.pt
- selected model: D:\Program\vision_service\models\yolo_fall_detector_phase8_selected.pt

## Test Benchmark

- v4: precision=0.2914, recall=0.2567, mAP50=0.1162, mAP50-95=0.0741
- v5: precision=0.1997, recall=0.3250, mAP50=0.1628, mAP50-95=0.1351

## Decision

- Select trained v5 as the Phase 8 candidate because recall and mAP improved over v4 on the merged test split.
- Do not use downloaded yolo11m.pt directly as a fall detector because it is COCO-pretrained and has no fall/fallen classes.
- Do not silently replace production default. First run real-camera hard-negative and fall-alert end-to-end tests.

## Recommended Runtime Trial

```text
YOLO_FALL_MODEL_PATH=models/yolo_fall_detector_phase8_selected.pt
TEMPORAL_MODEL_PROVIDER=shadow
```

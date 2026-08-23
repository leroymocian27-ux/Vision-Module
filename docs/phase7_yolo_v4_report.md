# Phase 7 YOLO v4 Report

Generated: 2026-06-07T01:59:47.673574+00:00

## Training Result

- status: partial_completed_timeout_after_epoch_2
- requested_epochs: 8
- completed_epochs: 2
- imgsz: 960
- batch: 8
- source_weight: D:\Program\model_test\fall_detection_model_bundle\v3_upgrade_lab\weights\yolo26\yolo26_fall_detector_v3_best.pt
- best_weight: D:\Program\vision_service\models\yolo_fall_detector_v4_best.pt

## Last Validation Metrics

- precision: 0.23856
- recall: 0.46744
- mAP50: 0.29327
- mAP50-95: 0.2195

## Dataset

- data_yaml: D:\Program\vision_service\models\yolo_fall_detector_v4_data.yaml
- yolo_images_have_labels: True

## Decision

- This is a versioned v4 trial detector, not a production default.
- Training was interrupted by the execution timeout after 2 epochs; continue training from runs/phase7_yolo_v4/fall_detector_v4/weights/last.pt for a stronger v4 candidate.
- Use it in shadow or fixed-camera limited trial only after runtime smoke passes.

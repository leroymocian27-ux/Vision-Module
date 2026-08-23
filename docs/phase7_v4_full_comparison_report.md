# Phase 7 v4 Full Comparison Report

Generated: 2026-06-07T02:00:51.811026+00:00

## Final Decision

- Production provider remains mock/rules.
- Recommended runtime provider remains shadow.
- YOLO v4 and LSTM v4 are versioned trial artifacts.
- onnx_lstm remains limited trial only; do not make it the default production provider.

## Dataset Gates

- unknown_adl_below_10_percent: True
- yolo_images_have_labels: True
- has_private_or_screen_replay_test: True

## YOLO v4

- status: partial_completed_timeout_after_epoch_2
- completed/requested epochs: 2/8
- last recall: 0.46744
- last mAP50: 0.29327

## LSTM v4

- ONNX validation passed: True
- max_abs_diff: 2.9802322387695312e-08
- best threshold: 0.6
- precision/recall/F1: 0.9231/0.4444/0.6

## v3 vs v4 Model-Layer Test

- v3 AUC: 0.6955
- v4 AUC: 0.6196
- v3 best FP: 9
- v4 best FP: 1
- v3 best recall: 0.4815
- v4 best recall: 0.4444

## Gate Result

- v4 reduces model-layer false positives at its calibrated threshold, but does not beat v3 AUC or recall.
- Keep v4 in shadow/fixed-camera limited trial until a longer YOLO training run and real camera state-machine evaluation pass.

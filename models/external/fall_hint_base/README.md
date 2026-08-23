# Fall Hint Base Weights

This directory stores base pretrained weights for future YOLO Fall Hint training.
Files here are not wired into the runtime chain directly.

## Selected Base

- File: `yolo11s_coco_fall_hint_base_2026-07-02.pt`
- Source: Ultralytics assets release `v8.3.0`
- Download URL: `https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11s.pt`
- SHA256: `85A76FE86DD8AFE384648546B56A7A78580C7CB7B404FC595F97969322D502D5`
- Task: YOLO detection
- Pretraining dataset/classes: COCO, 80 classes

## Intended Use

Use this as initialization for the project-specific YOLO Fall Hint detector:

- `0 falling`
- `1 fallen`
- `2 lying`
- `3 sitting`
- `4 bending`
- `5 kneeling`
- `6 standing`

The trained output must be evaluated before replacing the current runtime model.
Validation and test splits should use original reviewed data only, not augmented copies.
